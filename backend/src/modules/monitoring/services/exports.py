"""Cross-module loaders exposed through the monitoring contract.

Module-level functions (not service methods) in the style of the workspaces
loaders: a caller from another module owns the session and the transaction, and
imports these exclusively via ``contract.py``.

They exist for the finreports P&L, which needs figures the weekly settlement
report cannot supply:

* **Orders.** The settlement only sees what was bought out; заказы live in the
  sales-funnel history the monitoring harvest collects.
* **Advertising.** The settlement carries advertising only as account-level
  «WB Продвижение» invoices with no ``nm_id``. The per-SKU spend comes from the
  Promotion API's fullstats, which monitoring already ingests day by day.
* **Stock.** The «Баланс по товарным остаткам» table prices what is still lying
  in the warehouses; the settlement only ever describes goods that already
  moved. Remaining stock is a daily snapshot monitoring harvests per
  ``(day, SKU, warehouse, size)``.

All of them return plain mappings — no DTOs, no ORM rows — so the consumer stays
insulated from this module's internals. The catalogue-card loaders that used to
live here — "which SKU is this", rather than "what did this SKU earn" — moved to
:mod:`.cards` on 2026-09-05 under the same rules.

**Every loader here takes a ``workspace_id`` and every query is scoped by it,
through :func:`~src.modules.monitoring.repos.base.workspace_sku_select`.** Four
of them did not until 2026-08-27, and the consequence was not a missing filter
in the abstract: ``GET /pnl/skus`` summed EVERY tenant's orders and advertising
spend into the «Итого» row of whichever tenant asked. A monitoring loader
without a tenant argument is the bug, so none of them has an optional one — a
caller that does not know whose numbers it wants must not be able to compile.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    ProductCard,
    SalesFunnelDaily,
    StockSnapshot,
)
from src.modules.monitoring.repos.base import workspace_sku_select


async def load_orders_by_nm(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> dict[int, int]:
    """Return ordered units per SKU for the window, from the funnel history.

    The funnel history starts much later than the settlement history (first day
    on record: 2026-06-11), so a window that predates it legitimately returns an
    empty mapping — the caller must distinguish "no data" from "0 orders" by
    checking :func:`funnel_coverage` rather than assuming zeroes.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``{nm_id: Σ order_count}``; SKUs with no funnel rows are absent.
    """
    stmt = (
        select(SalesFunnelDaily.nm_id, func.sum(SalesFunnelDaily.order_count))
        .where(
            SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            SalesFunnelDaily.stat_date >= date_from,
            SalesFunnelDaily.stat_date <= date_to,
        )
        .group_by(SalesFunnelDaily.nm_id)
    )
    return {int(nm): int(total or 0) for nm, total in (await session.execute(stmt)).all()}


async def load_ad_spend_by_nm(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> dict[int, Decimal]:
    """Return advertising spend per SKU for the window, from the Promotion API.

    This is spend as WB's advertising statistics report it, dated by the day the
    ads ran — not the day the invoice was withheld from a settlement. The two
    reconcile only approximately (invoices lag the spend by up to a week), which
    is fine for a per-SKU cost attribution and wrong for an audit of the
    account-level «Удержания» line; use the settlement itself for that.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``{nm_id: Σ spend}``; SKUs that ran no ads are absent.
    """
    stmt = (
        select(AdvertisingStatDaily.nm_id, func.sum(AdvertisingStatDaily.spend))
        .where(
            AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .group_by(AdvertisingStatDaily.nm_id)
    )
    return {int(nm): Decimal(total) for nm, total in (await session.execute(stmt)).all()}


async def funnel_coverage(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> tuple[date | None, date | None]:
    """Return the funnel days actually on record inside a window.

    Lets a consumer say «заказы известны с 2026-06-11» instead of printing 0
    orders for two years the funnel never saw.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``(first, last)`` covered day inside the window, or ``(None, None)``.
    """
    stmt = select(func.min(SalesFunnelDaily.stat_date), func.max(SalesFunnelDaily.stat_date)).where(
        SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
        SalesFunnelDaily.stat_date >= date_from,
        SalesFunnelDaily.stat_date <= date_to,
    )
    first, last = (await session.execute(stmt)).one()
    return first, last


async def ad_coverage(
    session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
) -> tuple[date | None, date | None]:
    """Return the advertising days actually on record inside a window.

    Same caveat as :func:`funnel_coverage`: the Promotion API history begins
    2026-05-15, long after the settlement history. Scoped to the workspace for
    the same reason as the rest — an unscoped span would tell one tenant when
    ANOTHER tenant's advertising history starts.
    """
    stmt = select(
        func.min(AdvertisingStatDaily.stat_date), func.max(AdvertisingStatDaily.stat_date)
    ).where(
        AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
        AdvertisingStatDaily.stat_date >= date_from,
        AdvertisingStatDaily.stat_date <= date_to,
    )
    first, last = (await session.execute(stmt)).one()
    return first, last


async def stock_day_span(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> tuple[date | None, date | None]:
    """Return the first and last day a stock snapshot exists for the workspace.

    Stock is a point-in-time snapshot with no carry-over: a day WB never
    reported simply has no rows, and showing it as an empty balance would read
    as «всё распродано». The span bounds the balance table's day picker so only
    days that were actually captured can be asked for.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.

    Returns:
        ``(first, last)`` snapshot day, or ``(None, None)`` when nothing was
        ever harvested for this workspace.
    """
    stmt = select(func.min(StockSnapshot.stat_date), func.max(StockSnapshot.stat_date)).where(
        StockSnapshot.nm_id.in_(workspace_sku_select(workspace_id))
    )
    first, last = (await session.execute(stmt)).one()
    return first, last


class WarehouseStock(NamedTuple):
    """One SKU's units at one warehouse, split by where they physically are.

    ``in_way`` folds WB's two directions together — ``inWayToClient`` (sold,
    riding to a buyer who may still refuse it) and ``inWayFromClient`` (refused,
    riding back). Both are goods the seller has already paid for and will get
    back or get paid for, so a balance that priced only ``quantity`` would
    understate the money tied up in the warehouse by exactly the goods in motion.
    They are kept apart from ``quantity`` rather than added into it because only
    ``quantity`` can be shipped today.
    """

    quantity: int
    in_way: int


async def load_stock_by_warehouse(
    session: AsyncSession, *, workspace_id: uuid.UUID, stat_date: date
) -> dict[tuple[int, str], WarehouseStock]:
    """Return one day's remaining and in-transit stock per SKU and warehouse.

    Summed across sizes in SQL: the balance table is a SKU x warehouse grid, and
    a size grain would multiply a few thousand rows into tens of thousands the
    consumer would only fold back together. Cells empty on BOTH counts are
    dropped — WB omits emptied rows from its own report anyway, so an explicit
    zero carries no more meaning than an absent row — but a warehouse holding
    nothing while goods ride back to it survives, because that is money in
    motion and the whole reason in-transit is reported at all.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        stat_date: The exact snapshot day (never a carried-over neighbour).

    Returns:
        ``{(nm_id, warehouse_name): WarehouseStock}``; empty when the day has no
        snapshot.
    """
    quantity = func.sum(StockSnapshot.quantity)
    in_way = func.sum(StockSnapshot.in_way_to_client) + func.sum(StockSnapshot.in_way_from_client)
    stmt = (
        select(StockSnapshot.nm_id, StockSnapshot.warehouse_name, quantity, in_way)
        .where(
            StockSnapshot.stat_date == stat_date,
            StockSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
        )
        .group_by(StockSnapshot.nm_id, StockSnapshot.warehouse_name)
        .having((quantity != 0) | (in_way != 0))
    )
    rows = (await session.execute(stmt)).all()
    return {
        (int(nm_id), str(warehouse)): WarehouseStock(int(units), int(moving or 0))
        for nm_id, warehouse, units, moving in rows
    }


async def load_vendor_codes(session: AsyncSession, *, workspace_id: uuid.UUID) -> dict[int, str]:
    """Return the workspace's catalogue vendor codes («Артикул продавца»).

    The identity fallback for a SKU that holds stock but has never appeared in a
    settlement — a fresh supply, or one that never sold — and so has no name
    anywhere in the finreports tables. Without it such a row renders as a bare
    ``nm_id`` on a table whose first column is «Артикул».

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.

    Returns:
        ``{nm_id: vendor_code}``; SKUs whose card carries no code are absent.
    """
    stmt = select(ProductCard.nm_id, ProductCard.vendor_code).where(
        ProductCard.workspace_id == workspace_id, ProductCard.vendor_code != ""
    )
    return {int(nm_id): str(code) for nm_id, code in (await session.execute(stmt)).all()}


class AdDay(NamedTuple):
    """One SKU's advertising day, summed over campaigns and platforms.

    The A/B-tests module consumes this instead of calling ``fullstats`` itself:
    the harvest already pays that endpoint's ~1-request-per-minute toll, and a
    second caller on the same token would push the bucket over — which WB
    answers with a 500 or a hung socket rather than a clean 429.
    """

    stat_date: date
    views: int
    clicks: int
    atbs: int
    orders: int
    spend: Decimal


async def load_ad_days_for_nm(
    session: AsyncSession, *, workspace_id: uuid.UUID, nm_id: int, date_from: date, date_to: date
) -> list[AdDay]:
    """Return one SKU's advertising days over a window.

    Rows are summed across every campaign and platform that served the card, in
    line with how a campaign-day is split in ``fullstats`` — reading a single
    bucket as "the day" understates every metric.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The workspace the SKU must belong to. WB ids are globally
            unique, so filtering by ``nm_id`` alone is *usually* equivalent —
            but "usually" is not a property to build tenancy on, and a SKU
            tracked by two workspaces (a demo copy, a migration mid-flight)
            would silently answer for the wrong one. Every loader here takes a
            tenant so none of them has to be reasoned about individually.
        nm_id: SKU to report.
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        Days in ascending order; days with no advertising are absent. A SKU
        that does not belong to this workspace returns an empty list rather
        than another tenant's advertising.
    """
    stmt = (
        select(
            AdvertisingStatDaily.stat_date,
            func.sum(AdvertisingStatDaily.views),
            func.sum(AdvertisingStatDaily.clicks),
            func.sum(AdvertisingStatDaily.add_to_cart),
            func.sum(AdvertisingStatDaily.orders),
            func.sum(AdvertisingStatDaily.spend),
        )
        .where(
            AdvertisingStatDaily.nm_id == nm_id,
            AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .group_by(AdvertisingStatDaily.stat_date)
        .order_by(AdvertisingStatDaily.stat_date)
    )
    return [
        AdDay(
            stat_date=row[0],
            views=int(row[1] or 0),
            clicks=int(row[2] or 0),
            atbs=int(row[3] or 0),
            orders=int(row[4] or 0),
            spend=Decimal(row[5] or 0),
        )
        for row in (await session.execute(stmt)).all()
    ]


async def load_campaign_ids_for_workspace(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    since_days: int = 30,
    nm_ids: Sequence[int] | None = None,
) -> list[int]:
    """Return the campaigns that recently served one workspace's SKUs.

    ``monitoring.campaigns`` is a global table — WB campaign ids are not
    namespaced by tenant and the row carries no workspace — so the tenancy comes
    from the traffic instead: a campaign belongs to this workspace's world if it
    served a SKU this workspace owns. That is the same ``product_card`` semijoin
    every other cross-SKU aggregate here uses.

    The A/B poller asks for this because ``fullstats`` is addressed by campaign
    id, not by SKU: to read one card's counters you have to name the campaigns
    that might be serving it.

    A campaign created since the last harvest is absent until the harvest sees
    it, so a test started on a brand-new campaign reads zero traffic for up to a
    day. That is a lag in discovery, not in attribution — once the campaign
    appears, its counters are read cumulatively from midnight and nothing is
    lost.

    **Narrow it with ``nm_ids`` when you know which cards you care about.** The
    result is what a fullstats request is addressed by, and that request takes
    fifty ids at a time on a bucket refilling once every twenty seconds — so an
    id that cannot possibly carry the traffic being asked for is not free, it is
    a share of a fifty-slot batch and potentially a twenty-second wait. A
    cabinet advertising four hundred SKUs while testing three of them was
    sending eight batches where one would do.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The workspace whose campaigns to return.
        since_days: How far back a campaign must have served to count.
        nm_ids: Restrict to campaigns that served these cards. ``None`` keeps
            the whole workspace's catalogue, which is what the exports want and
            what the A/Б poller deliberately does not.

    Returns:
        Campaign ids, ascending.
    """
    cutoff = moscow_today() - timedelta(days=since_days)
    served = (
        AdvertisingStatDaily.nm_id.in_(list(nm_ids))
        if nm_ids is not None
        else AdvertisingStatDaily.nm_id.in_(workspace_sku_select(workspace_id))
    )
    stmt = (
        select(AdvertisingStatDaily.campaign_id)
        .where(
            AdvertisingStatDaily.stat_date >= cutoff,
            served,
        )
        .group_by(AdvertisingStatDaily.campaign_id)
        .order_by(AdvertisingStatDaily.campaign_id)
    )
    return [int(row[0]) for row in (await session.execute(stmt)).all()]
