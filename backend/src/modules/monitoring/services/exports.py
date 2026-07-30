"""Cross-module loaders exposed through the monitoring contract.

Module-level functions (not service methods) in the style of the workspaces
loaders: a caller from another module owns the session and the transaction, and
imports these exclusively via ``contract.py``.

They exist for the finreports P&L, which needs two figures per SKU the weekly
settlement report cannot supply:

* **Orders.** The settlement only sees what was bought out; заказы live in the
  sales-funnel history the monitoring harvest collects.
* **Advertising.** The settlement carries advertising only as account-level
  «WB Продвижение» invoices with no ``nm_id``. The per-SKU spend comes from the
  Promotion API's fullstats, which monitoring already ingests day by day.

Both return plain ``{nm_id: value}`` mappings — no DTOs, no ORM rows — so the
consumer stays insulated from this module's internals.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingStatDaily, SalesFunnelDaily


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
