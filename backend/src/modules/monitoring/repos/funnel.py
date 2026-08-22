"""Repository for :class:`SalesFunnelDaily` rows."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import PriceSnapshot, SalesFunnelDaily
from src.modules.monitoring.repos.base import BaseRepository, workspace_sku_select


@dataclass(frozen=True, slots=True)
class FunnelDayTotal:
    """One day of funnel facts, summed across the SKUs in scope.

    ``sku_count`` is how many cards contributed — the honest denominator for
    reading the day, and what tells a blank stretch («no card reported») apart
    from a real zero.

    ``order_sum`` is ``None`` when not one contributing SKU-day carried a price,
    matching the per-SKU matrix, which leaves «Заказы, ₽» blank rather than
    calling an unpriced day zero roubles.
    """

    stat_date: date
    sku_count: int
    open_count: int
    cart_count: int
    order_count: int
    buyout_count: int
    order_sum: float | None


@dataclass(frozen=True, slots=True)
class FunnelAggregate:
    """Window totals for one SKU, computed by the database.

    Aggregating in SQL keeps the summary endpoint O(SKUs) in memory instead of
    hydrating every daily fact row in the window.
    """

    nm_id: int
    days_count: int
    open_count: int
    cart_count: int
    order_count: int
    buyout_count: int
    add_to_wishlist: int


_CONFLICT = ("stat_date", "nm_id")
#: Columns the DAILY HISTORY feed owns. ``buyout_count`` is deliberately absent:
#: the history feed still seeds it when it INSERTs a new day, but the cohort
#: pass (:meth:`FunnelRepository.upsert_cohorts`) owns it from then on. Letting
#: history overwrite it would walk the matured value back to the <=7-day-old
#: figure on every harvest — the history endpoint only serves the last 7 days,
#: so its buyout counts are always the immature ones.
_UPDATE = (
    "open_count",
    "cart_count",
    "order_count",
    "add_to_wishlist",
    "cart_conversion",
    "order_conversion",
    "buyout_conversion",
)
#: Columns the period-aggregate cohort pass owns — the «Процент выкупа» inputs.
_COHORT_UPDATE = ("buyout_count", "cancel_count")


class FunnelRepository(BaseRepository):
    """CRUD/read operations for daily organic funnel metrics."""

    model = SalesFunnelDaily

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of flattened funnel rows.

        Args:
            rows: Column->value mappings keyed by ``(stat_date, nm_id)``.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def update_cohorts(self, rows: list[dict[str, object]]) -> int:
        """Refresh the matured buyout/cancel counts of existing cohort days.

        Separate from :meth:`upsert_many` because the two feeds own different
        columns of the same row: the daily history endpoint owns the funnel
        counts, while the period aggregate owns ``buyout_count``/``cancel_count``
        (it is the only source of the latter, and the only one that can re-read
        a cohort older than 7 days as it matures).

        Strictly an UPDATE: rows whose ``(stat_date, nm_id)`` has no funnel day
        are dropped. The aggregate returns the whole catalogue for any date the
        seller ever traded, so inserting blind would fabricate zero-order funnel
        days for SKUs/dates we never harvested — days the matrix currently (and
        correctly) renders as «—».

        Args:
            rows: ``{stat_date, nm_id, buyout_count, cancel_count}`` mappings.

        Returns:
            The number of cohort days actually refreshed.
        """
        if not rows:
            return 0
        dates = {row["stat_date"] for row in rows}
        stmt = select(SalesFunnelDaily.stat_date, SalesFunnelDaily.nm_id).where(
            SalesFunnelDaily.stat_date.in_(dates)
        )
        result = await self._session.execute(stmt)
        existing = {(row.stat_date, row.nm_id) for row in result.all()}
        known = [row for row in rows if (row["stat_date"], row["nm_id"]) in existing]
        return await self.bulk_upsert(
            known, conflict_columns=_CONFLICT, update_columns=_COHORT_UPDATE
        )

    async def list_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[SalesFunnelDaily]:
        """Return all funnel rows for one SKU within an inclusive window.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            Funnel rows ordered by ascending date.
        """
        stmt = (
            select(SalesFunnelDaily)
            .where(
                SalesFunnelDaily.nm_id == nm_id,
                SalesFunnelDaily.stat_date >= date_from,
                SalesFunnelDaily.stat_date <= date_to,
            )
            .order_by(SalesFunnelDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def daily_totals(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        nm_ids: Sequence[int] | None = None,
    ) -> list[FunnelDayTotal]:
        """Return per-DAY funnel totals summed ACROSS SKUs, with order revenue.

        The sibling of :meth:`aggregate_window`, grouped the other way: that one
        answers «what did each SKU do over the window», this one «what did the
        whole account do on each day» — the series the «Графики» page draws.

        ``order_sum`` is ``Σ(order_count x seller_price)`` over the SKUs of a
        day, not ``Σorders x some price``: each card is worth its own price, so
        the join to the price snapshot happens BEFORE the sum. A SKU-day with no
        price snapshot contributes its counts and nothing to the revenue, the
        same silence the per-SKU matrix keeps («Заказы, ₽» is ``None`` when
        unpriced) rather than valuing it at zero.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            nm_ids: Restrict further to these SKUs; ``None`` means all of them.

        Returns:
            One :class:`FunnelDayTotal` per day with data, ascending by date.
        """
        revenue = func.sum(SalesFunnelDaily.order_count * PriceSnapshot.seller_price)
        stmt = (
            select(
                SalesFunnelDaily.stat_date,
                func.count().label("sku_count"),
                func.sum(SalesFunnelDaily.open_count).label("open_count"),
                func.sum(SalesFunnelDaily.cart_count).label("cart_count"),
                func.sum(SalesFunnelDaily.order_count).label("order_count"),
                func.sum(SalesFunnelDaily.buyout_count).label("buyout_count"),
                revenue.label("order_sum"),
            )
            .outerjoin(
                PriceSnapshot,
                (PriceSnapshot.nm_id == SalesFunnelDaily.nm_id)
                & (PriceSnapshot.stat_date == SalesFunnelDaily.stat_date),
            )
            .where(
                SalesFunnelDaily.stat_date >= date_from,
                SalesFunnelDaily.stat_date <= date_to,
                SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            )
            .group_by(SalesFunnelDaily.stat_date)
            .order_by(SalesFunnelDaily.stat_date)
        )
        if nm_ids is not None:
            stmt = stmt.where(SalesFunnelDaily.nm_id.in_(list(nm_ids)))
        result = await self._session.execute(stmt)
        return [
            FunnelDayTotal(
                stat_date=row.stat_date,
                sku_count=int(row.sku_count),
                open_count=int(row.open_count),
                cart_count=int(row.cart_count),
                order_count=int(row.order_count),
                buyout_count=int(row.buyout_count),
                order_sum=None if row.order_sum is None else float(row.order_sum),
            )
            for row in result.all()
        ]

    async def aggregate_window(
        self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[FunnelAggregate]:
        """Return per-SKU window totals, aggregated by the database.

        Used by the summary listing: SUM/GROUP BY in SQL returns one row per
        SKU, replacing the previous implementation that hydrated every daily
        fact row in the window (an OOM risk on wide windows).

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            One :class:`FunnelAggregate` per SKU with data in the window,
            ordered by SKU id.
        """
        stmt = (
            select(
                SalesFunnelDaily.nm_id,
                func.count().label("days_count"),
                func.sum(SalesFunnelDaily.open_count).label("open_count"),
                func.sum(SalesFunnelDaily.cart_count).label("cart_count"),
                func.sum(SalesFunnelDaily.order_count).label("order_count"),
                func.sum(SalesFunnelDaily.buyout_count).label("buyout_count"),
                func.sum(SalesFunnelDaily.add_to_wishlist).label("add_to_wishlist"),
            )
            .where(
                SalesFunnelDaily.stat_date >= date_from,
                SalesFunnelDaily.stat_date <= date_to,
                SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            )
            .group_by(SalesFunnelDaily.nm_id)
            .order_by(SalesFunnelDaily.nm_id)
        )
        result = await self._session.execute(stmt)
        return [
            FunnelAggregate(
                nm_id=row.nm_id,
                days_count=row.days_count,
                open_count=int(row.open_count),
                cart_count=int(row.cart_count),
                order_count=int(row.order_count),
                buyout_count=int(row.buyout_count),
                add_to_wishlist=int(row.add_to_wishlist),
            )
            for row in result.all()
        ]
