"""Repository for :class:`SalesFunnelDaily` rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import SalesFunnelDaily
from src.modules.monitoring.repos.base import BaseRepository

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

    async def list_window(self, *, date_from: date, date_to: date) -> list[SalesFunnelDaily]:
        """Return all funnel rows across every SKU within a window.

        Used by the summary listing to roll metrics up per SKU.
        """
        stmt = (
            select(SalesFunnelDaily)
            .where(
                SalesFunnelDaily.stat_date >= date_from,
                SalesFunnelDaily.stat_date <= date_to,
            )
            .order_by(SalesFunnelDaily.nm_id, SalesFunnelDaily.stat_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
