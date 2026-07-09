"""Repository for :class:`StockSnapshot` rows."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import StockSnapshot
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "nm_id", "warehouse_name", "chrt_id")
_UPDATE = ("region_name", "quantity", "in_way_to_client", "in_way_from_client")


class StockRepository(BaseRepository):
    """CRUD/read operations for daily per-warehouse stock snapshots."""

    model = StockSnapshot

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of per-warehouse stock rows.

        Args:
            rows: Column->value mappings keyed by ``(stat_date, nm_id,
                warehouse_name)``.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def list_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[StockSnapshot]:
        """Return stock snapshots for one SKU within an inclusive window."""
        stmt = (
            select(StockSnapshot)
            .where(
                StockSnapshot.nm_id == nm_id,
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
            )
            .order_by(StockSnapshot.stat_date, StockSnapshot.warehouse_name)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_window(self, *, date_from: date, date_to: date) -> list[StockSnapshot]:
        """Return stock snapshots across every SKU within a window."""
        stmt = (
            select(StockSnapshot)
            .where(
                StockSnapshot.stat_date >= date_from,
                StockSnapshot.stat_date <= date_to,
            )
            .order_by(StockSnapshot.nm_id, StockSnapshot.stat_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
