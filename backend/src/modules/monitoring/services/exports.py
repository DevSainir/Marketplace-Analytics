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
insulated from this module's internals.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    ProductCard,
    SalesFunnelDaily,
    StockSnapshot,
)
from src.modules.monitoring.repos.base import workspace_sku_select


async def load_orders_by_nm(
    session: AsyncSession, *, date_from: date, date_to: date
) -> dict[int, int]:
    """Return ordered units per SKU for the window, from the funnel history.

    The funnel history starts much later than the settlement history (first day
    on record: 2026-06-11), so a window that predates it legitimately returns an
    empty mapping — the caller must distinguish "no data" from "0 orders" by
    checking :func:`funnel_coverage` rather than assuming zeroes.

    Args:
        session: An open async session (caller owns the transaction).
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``{nm_id: Σ order_count}``; SKUs with no funnel rows are absent.
    """
    stmt = (
        select(SalesFunnelDaily.nm_id, func.sum(SalesFunnelDaily.order_count))
        .where(SalesFunnelDaily.stat_date >= date_from, SalesFunnelDaily.stat_date <= date_to)
        .group_by(SalesFunnelDaily.nm_id)
    )
    return {int(nm): int(total or 0) for nm, total in (await session.execute(stmt)).all()}


async def load_ad_spend_by_nm(
    session: AsyncSession, *, date_from: date, date_to: date
) -> dict[int, Decimal]:
    """Return advertising spend per SKU for the window, from the Promotion API.

    This is spend as WB's advertising statistics report it, dated by the day the
    ads ran — not the day the invoice was withheld from a settlement. The two
    reconcile only approximately (invoices lag the spend by up to a week), which
    is fine for a per-SKU cost attribution and wrong for an audit of the
    account-level «Удержания» line; use the settlement itself for that.

    Args:
        session: An open async session (caller owns the transaction).
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``{nm_id: Σ spend}``; SKUs that ran no ads are absent.
    """
    stmt = (
        select(AdvertisingStatDaily.nm_id, func.sum(AdvertisingStatDaily.spend))
        .where(
            AdvertisingStatDaily.stat_date >= date_from,
            AdvertisingStatDaily.stat_date <= date_to,
        )
        .group_by(AdvertisingStatDaily.nm_id)
    )
    return {int(nm): Decimal(total) for nm, total in (await session.execute(stmt)).all()}


async def funnel_coverage(
    session: AsyncSession, *, date_from: date, date_to: date
) -> tuple[date | None, date | None]:
    """Return the funnel days actually on record inside a window.

    Lets a consumer say «заказы известны с 2026-06-11» instead of printing 0
    orders for two years the funnel never saw.

    Args:
        session: An open async session (caller owns the transaction).
        date_from: Inclusive stat-date start.
        date_to: Inclusive stat-date end.

    Returns:
        ``(first, last)`` covered day inside the window, or ``(None, None)``.
    """
    stmt = select(func.min(SalesFunnelDaily.stat_date), func.max(SalesFunnelDaily.stat_date)).where(
        SalesFunnelDaily.stat_date >= date_from, SalesFunnelDaily.stat_date <= date_to
    )
    first, last = (await session.execute(stmt)).one()
    return first, last


async def ad_coverage(
    session: AsyncSession, *, date_from: date, date_to: date
) -> tuple[date | None, date | None]:
    """Return the advertising days actually on record inside a window.

    Same caveat as :func:`funnel_coverage`: the Promotion API history begins
    2026-05-15, long after the settlement history.
    """
    stmt = select(
        func.min(AdvertisingStatDaily.stat_date), func.max(AdvertisingStatDaily.stat_date)
    ).where(AdvertisingStatDaily.stat_date >= date_from, AdvertisingStatDaily.stat_date <= date_to)
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


async def load_stock_by_warehouse(
    session: AsyncSession, *, workspace_id: uuid.UUID, stat_date: date
) -> dict[tuple[int, str], int]:
    """Return one day's remaining stock per SKU and warehouse.

    Summed across sizes in SQL: the balance table is a SKU x warehouse grid, and
    a size grain would multiply a few thousand rows into tens of thousands the
    consumer would only fold back together. Zero-quantity cells are dropped — WB
    omits emptied rows from its own report anyway, so an explicit zero carries no
    more meaning than an absent row.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: Restrict to SKUs owned by this workspace.
        stat_date: The exact snapshot day (never a carried-over neighbour).

    Returns:
        ``{(nm_id, warehouse_name): Σ quantity}``; empty when the day has no
        snapshot.
    """
    total = func.sum(StockSnapshot.quantity)
    stmt = (
        select(StockSnapshot.nm_id, StockSnapshot.warehouse_name, total)
        .where(
            StockSnapshot.stat_date == stat_date,
            StockSnapshot.nm_id.in_(workspace_sku_select(workspace_id)),
        )
        .group_by(StockSnapshot.nm_id, StockSnapshot.warehouse_name)
        .having(total != 0)
    )
    rows = (await session.execute(stmt)).all()
    return {(int(nm_id), str(warehouse)): int(quantity) for nm_id, warehouse, quantity in rows}


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
