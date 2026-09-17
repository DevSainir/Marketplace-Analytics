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
from src.modules.monitoring.repos.orders import OrderRepository

#: Neutral element for the money sums below.
_ZERO = Decimal(0)


class OrderDay(NamedTuple):
    """One ordered day, summed over every SKU the workspace owns.

    Two sources answer this, and they reach different distances. WB's analytics
    funnel is what a кабинет has from the day this service started harvesting
    it; the statistics ORDERS feed answers from any date, so it is what the
    history before that comes from. A day the funnel covers is reported from the
    funnel — that is the number every other screen shows — and the rest from the
    order lines.

    ``buyouts`` is therefore ``None`` on a day only the order feed reaches: the
    funnel's buyout cohort is the only source for it, and a zero there would
    read as «ничего не выкупили» on months that simply predate the harvest.

    The two money figures are what «ДРР от заказов» divides by, at whichever
    price base the reader picked. They come from the order lines when there are
    any — each line carries its own price — and otherwise from
    ``Σ(order_count x snapshotted price)``, which has no after-СПП half at all.
    ``None`` means neither was available: a day we cannot value, which must not
    be valued at zero.
    """

    stat_date: date
    orders: int
    buyouts: int | None
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
    """Return the workspace's ordered units per day, from both sources.

    Days no source covers are ABSENT from the result rather than zero — that is
    "we do not know", not "nobody ordered". Filling a gap in the harvest with
    zeroes would make it indistinguishable from a day of no demand.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        Days in ascending date order.
    """
    funnel = await _funnel_days(
        session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
    )
    ordered = {
        row.order_date: row
        for row in await OrderRepository(session).day_totals(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
    }

    days: list[OrderDay] = []
    for day in sorted(funnel.keys() | ordered.keys()):
        from_funnel = funnel.get(day)
        from_orders = ordered.get(day)
        days.append(
            OrderDay(
                stat_date=day,
                # The funnel first where it reaches: it is WB's own analytics
                # count, and it is what «Сравнение SKU» shows for the same day.
                orders=from_funnel.orders
                if from_funnel
                else (from_orders.orders if from_orders else 0),
                buyouts=from_funnel.buyouts if from_funnel else None,
                amount_seller=(
                    from_orders.amount_seller
                    if from_orders
                    else (from_funnel.amount if from_funnel else None)
                ),
                amount_paid=from_orders.amount_paid if from_orders else None,
            )
        )
    return days


class _FunnelDay(NamedTuple):
    """One funnel day: counts, and the value the price snapshots can give it."""

    orders: int
    buyouts: int
    amount: Decimal | None


async def _funnel_days(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> dict[date, _FunnelDay]:
    """The analytics funnel's own days, valued at the snapshotted prices.

    The join to the price snapshot happens BEFORE the sum, because each card is
    worth its own price; a SKU-day with no snapshot contributes its counts and
    nothing to the money, which is the same silence the per-SKU matrix keeps.
    """
    stmt = (
        select(
            SalesFunnelDaily.stat_date,
            func.sum(SalesFunnelDaily.order_count),
            func.sum(SalesFunnelDaily.buyout_count),
            func.sum(SalesFunnelDaily.order_count * PriceSnapshot.seller_price),
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
    return {
        day: _FunnelDay(
            orders=int(orders or 0),
            buyouts=int(buyouts or 0),
            amount=None if amount is None else Decimal(amount),
        )
        for day, orders, buyouts, amount in (await session.execute(stmt)).all()
    }


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
