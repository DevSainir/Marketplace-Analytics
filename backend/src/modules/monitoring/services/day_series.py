"""Whole-workspace daily series — the cut the per-SKU loaders cannot give.

:mod:`.exports` answers "how much did each SKU do over the window"; these two
answer "how much did the whole account do on each day". The difference is not
cosmetic: a summary chart is drawn per day, and building it out of the per-SKU
cuts would mean pulling the entire SKU-by-day matrix into memory.

Tenancy is the same as its neighbours' — the ``product_card`` semijoin — because
neither the funnel nor the campaign statistics carries a ``workspace_id`` of its
own.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    BONUS_PAYMENT_TYPES,
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.base import workspace_sku_select

#: Neutral element for the money sums below.
_ZERO = Decimal(0)


class OrderDay(NamedTuple):
    """One funnel day, summed over every SKU the workspace owns.

    ``decided`` is deliveries the buyer has ANSWERED — bought out or refused —
    which is the denominator WB's own «Процент выкупа» uses and the matrix has
    used since it was written. Orders still in transit are in neither half, so
    the ratio does not start near zero and climb for three weeks the way
    buyouts-over-orders does. It is ``None`` where the cohort pass has never
    refreshed the day, which is not «nothing was refused» but «we have not been
    told yet».

    The two money figures are what «ДРР от заказов» divides by, at whichever
    price base the reader picked: ``Σ(заказы x цена)`` with the day's own price
    snapshot, joined BEFORE the sum because each card is worth its own price.
    ``None`` when not one SKU of that day carried a snapshot — WB's funnel
    publishes no money volume at all, so a day we never priced has no volume,
    and zero there would read as infinite ДРР.
    """

    stat_date: date
    orders: int
    buyouts: int | None
    decided: int | None
    #: Σ the seller's own price, before WB's СПП.
    amount_seller: Decimal | None
    #: Σ what the customer pays, СПП applied.
    amount_paid: Decimal | None


class AdSpendDay(NamedTuple):
    """One advertising day: what ran, and how much of it WB paid for.

    ``spend`` is the whole burn as the cabinet reports it, whoever funded it.
    ``bonus`` is the part WB covered from its own pool. What the seller actually
    paid is the difference, and the consumer is the one who takes it: the two
    figures apart read differently from one figure already netted.
    """

    stat_date: date
    spend: Decimal
    bonus: Decimal


async def load_order_days(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> list[OrderDay]:
    """Return the workspace's ordered units per day, from WB's analytics funnel.

    Days with no funnel row at all are ABSENT from the result rather than zero —
    that is "we do not know", not "nobody ordered". A gap in coverage is what
    :func:`funnel_coverage` reports, and filling it with zeroes here would make a
    hole in the harvest indistinguishable from a day of no demand.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        Days in ascending date order.
    """
    # A SKU-day whose `cancel_count` is still NULL has never been through the
    # cohort pass: counting it as «no refusals» would invent a 100 % cohort, so
    # its buyouts stay out of the decided sum entirely — the same exclusion the
    # matrix makes, and the reason «Процент выкупа» there reads WB's own figure.
    decided = func.sum(SalesFunnelDaily.buyout_count + SalesFunnelDaily.cancel_count).filter(
        SalesFunnelDaily.cancel_count.is_not(None)
    )
    stmt = (
        select(
            SalesFunnelDaily.stat_date,
            func.sum(SalesFunnelDaily.order_count),
            func.sum(SalesFunnelDaily.buyout_count),
            decided,
            func.sum(SalesFunnelDaily.order_count * PriceSnapshot.seller_price),
            func.sum(SalesFunnelDaily.order_count * PriceSnapshot.customer_price),
        )
        .outerjoin(
            PriceSnapshot,
            (PriceSnapshot.nm_id == SalesFunnelDaily.nm_id)
            & (PriceSnapshot.stat_date == SalesFunnelDaily.stat_date),
        )
        .where(
            SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            SalesFunnelDaily.stat_date >= date_from,
            SalesFunnelDaily.stat_date <= date_to,
        )
        .group_by(SalesFunnelDaily.stat_date)
        .order_by(SalesFunnelDaily.stat_date)
    )
    return [
        OrderDay(
            stat_date=day,
            orders=int(orders or 0),
            buyouts=int(buyouts or 0),
            decided=None if decided_units is None else int(decided_units),
            amount_seller=None if seller is None else Decimal(seller),
            amount_paid=None if paid is None else Decimal(paid),
        )
        for day, orders, buyouts, decided_units, seller, paid in (await session.execute(stmt)).all()
    ]


async def load_ad_days(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> list[AdSpendDay]:
    """Return the workspace's advertising burn per day, and its bonus-funded part.

    The bonus is NOT allocated to SKUs here, and that makes it sounder than the
    per-SKU figure rather than weaker: WB's write-off ledger is keyed by campaign,
    never by ``nm_id``, so spreading it over SKUs is a model
    (see :func:`load_ad_bonus_by_nm`). At account level no model is needed — the
    same ledger rows are simply summed.

    **Both numbers are raw daily sums, and a day's bonus can exceed its spend.**
    Write-offs are batched — one row at 22:45 against a whole day of impressions
    — so the two feeds only line up over a window, not day by day. Netting them
    here would hand out a negative "paid by the seller" on a day that was
    nothing of the sort, so the decision is left to the consumer, which knows
    what its window is: spreading the window's bonus across the days in
    proportion to their spend keeps the series summable AND non-negative.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        Days in ascending date order; a day with no burn is absent.
    """
    spend_stmt = (
        select(AdvertisingStatDaily.stat_date, func.sum(AdvertisingStatDaily.spend))
        .where(
            AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .group_by(AdvertisingStatDaily.stat_date)
    )
    spend_by_day = {
        day: Decimal(total or 0) for day, total in (await session.execute(spend_stmt)).all()
    }

    # This workspace's campaigns are the ones that served its SKUs in this
    # window — the same semijoin every other cross-SKU aggregate uses, because
    # the campaigns table carries no workspace of its own.
    campaigns = (
        select(AdvertisingStatDaily.campaign_id)
        .where(
            AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .distinct()
    )
    bonus_stmt = (
        select(AdvertisingWriteOffDaily.stat_date, func.sum(AdvertisingWriteOffDaily.amount))
        .where(
            AdvertisingWriteOffDaily.campaign_id.in_(campaigns),
            AdvertisingWriteOffDaily.stat_date >= date_from,
            AdvertisingWriteOffDaily.stat_date <= date_to,
            AdvertisingWriteOffDaily.payment_type.in_(sorted(BONUS_PAYMENT_TYPES)),
        )
        .group_by(AdvertisingWriteOffDaily.stat_date)
    )
    bonus_by_day = {
        day: Decimal(total or 0) for day, total in (await session.execute(bonus_stmt)).all()
    }

    return [
        AdSpendDay(stat_date=day, spend=spend, bonus=bonus_by_day.get(day, _ZERO))
        for day, spend in sorted(spend_by_day.items())
    ]
