"""Data access for per-SKU warehouse marks («Отгрузить» flags).

Sole owner of SQL for ``monitoring.warehouse_mark`` — services depend on this
repository and never issue queries themselves. Presence of a row means the
warehouse is marked for that SKU; unmarking deletes the row, so both writes
are idempotent.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.warehouse_marks import WarehouseMark


class WarehouseMarkRepository:
    """Reads and writes the per-SKU warehouse marks."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def list_names(self, *, nm_id: int) -> list[str]:
        """Return the SKU's marked warehouse names, alphabetically.

        Args:
            nm_id: WB SKU identifier.

        Returns:
            The marked ``warehouse_name`` values (empty when none are marked).
        """
        stmt = (
            select(WarehouseMark.warehouse_name)
            .where(WarehouseMark.nm_id == nm_id)
            .order_by(WarehouseMark.warehouse_name)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, *, nm_id: int, warehouse_name: str) -> None:
        """Mark a warehouse for the SKU (no-op when already marked).

        Args:
            nm_id: WB SKU identifier.
            warehouse_name: WB warehouse name as reported by the stocks report.
        """
        stmt = (
            pg_insert(WarehouseMark)
            .values(nm_id=nm_id, warehouse_name=warehouse_name)
            .on_conflict_do_nothing(
                index_elements=[WarehouseMark.nm_id, WarehouseMark.warehouse_name]
            )
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the mark before the request-level commit.
        await self._session.flush()

    async def remove(self, *, nm_id: int, warehouse_name: str) -> None:
        """Unmark a warehouse for the SKU (no-op when not marked).

        Args:
            nm_id: WB SKU identifier.
            warehouse_name: WB warehouse name as reported by the stocks report.
        """
        stmt = delete(WarehouseMark).where(
            WarehouseMark.nm_id == nm_id,
            WarehouseMark.warehouse_name == warehouse_name,
        )
        await self._session.execute(stmt)
        await self._session.flush()
