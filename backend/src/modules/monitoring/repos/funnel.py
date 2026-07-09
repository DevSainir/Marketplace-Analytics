"""Repository for :class:`SalesFunnelDaily` rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import SalesFunnelDaily
from src.modules.monitoring.repos.base import BaseRepository


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
    order_sum: float
    buyout_count: int
    buyout_sum: float
    add_to_wishlist: int


_CONFLICT = ("stat_date", "nm_id")
_UPDATE = (
    "open_count",
    "cart_count",
    "order_count",
    "order_sum",
    "buyout_count",
    "buyout_sum",
    "add_to_wishlist",
    "cart_conversion",
    "order_conversion",
    "buyout_conversion",
)


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

    async def aggregate_window(self, *, date_from: date, date_to: date) -> list[FunnelAggregate]:
        """Return per-SKU window totals, aggregated by the database.

        Used by the summary listing: SUM/GROUP BY in SQL returns one row per
        SKU, replacing the previous implementation that hydrated every daily
        fact row in the window (an OOM risk on wide windows).

        Args:
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
                func.sum(SalesFunnelDaily.order_sum).label("order_sum"),
                func.sum(SalesFunnelDaily.buyout_count).label("buyout_count"),
                func.sum(SalesFunnelDaily.buyout_sum).label("buyout_sum"),
                func.sum(SalesFunnelDaily.add_to_wishlist).label("add_to_wishlist"),
            )
            .where(
                SalesFunnelDaily.stat_date >= date_from,
                SalesFunnelDaily.stat_date <= date_to,
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
                order_sum=float(row.order_sum),
                buyout_count=int(row.buyout_count),
                buyout_sum=float(row.buyout_sum),
                add_to_wishlist=int(row.add_to_wishlist),
            )
            for row in result.all()
        ]
