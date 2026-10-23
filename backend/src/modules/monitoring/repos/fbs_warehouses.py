"""Repository for :class:`FbsWarehouse` rows — the discovered FBS directory."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import FbsWarehouse
from src.modules.monitoring.repos.base import BaseRepository


class FbsWarehouseRepository(BaseRepository):
    """Read/write access to the seller's known FBS warehouses."""

    model = FbsWarehouse

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def list_all(self) -> list[FbsWarehouse]:
        """Return every warehouse ever discovered, oldest first.

        Includes warehouses WB has stopped listing: their stock history is
        still filed under their labels, and the harvest's stale-row sweep has
        to know those labels to leave them alone.
        """
        result = await self._session.execute(
            select(FbsWarehouse).order_by(FbsWarehouse.discovered_at, FbsWarehouse.warehouse_id)
        )
        return list(result.scalars().all())

    async def remember(self, *, warehouse_id: int, label: str, wb_name: str) -> FbsWarehouse:
        """Record a warehouse seen in this run, and return the stored row.

        First sight stores the resolved ``label``; every later sight only
        refreshes ``last_seen_at`` and WB's current name. The label is NEVER
        rewritten — it is a primary-key value in ``stock_snapshot``, so moving
        it would orphan the warehouse's whole stock history and its
        "Ship" marks (see :class:`FbsWarehouse`).

        Args:
            warehouse_id: WB id of the seller warehouse.
            label: The label to freeze if this warehouse is new.
            wb_name: WB's current name for it (diagnostic).

        Returns:
            The stored row — carrying the label already in force when the
            warehouse was known before.
        """
        known = await self._session.get(FbsWarehouse, warehouse_id)
        if known is None:
            known = FbsWarehouse(warehouse_id=warehouse_id, label=label, wb_name=wb_name)
            self._session.add(known)
            await self._session.flush()
            return known
        await self._session.execute(
            update(FbsWarehouse)
            .where(FbsWarehouse.warehouse_id == warehouse_id)
            .values(wb_name=wb_name, last_seen_at=func.now())
        )
        return known
