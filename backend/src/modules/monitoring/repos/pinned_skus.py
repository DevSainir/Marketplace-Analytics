"""Data access for globally pinned SKUs («Закрепить» flags).

Sole owner of SQL for ``monitoring.pinned_sku`` — services depend on this
repository and never issue queries themselves. Presence of a row means the SKU
is pinned; unpinning deletes the row, so both writes are idempotent.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.pinned_skus import PinnedSku


class PinnedSkuRepository:
    """Reads and writes the global pinned-SKU list."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def list_ids(self) -> list[int]:
        """Return every pinned ``nm_id`` in pin order (oldest pin first).

        Returns:
            The pinned SKU identifiers (empty when nothing is pinned).
        """
        stmt = select(PinnedSku.nm_id).order_by(PinnedSku.created_at, PinnedSku.nm_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, *, nm_id: int) -> None:
        """Pin a SKU (no-op when already pinned).

        Args:
            nm_id: WB SKU identifier to pin.
        """
        stmt = (
            pg_insert(PinnedSku)
            .values(nm_id=nm_id)
            .on_conflict_do_nothing(index_elements=[PinnedSku.nm_id])
        )
        await self._session.execute(stmt)
        # The session runs with autoflush disabled — flush so a follow-up read
        # in the same request sees the pin before the request-level commit.
        await self._session.flush()

    async def remove(self, *, nm_id: int) -> None:
        """Unpin a SKU (no-op when not pinned).

        Args:
            nm_id: WB SKU identifier to unpin.
        """
        stmt = delete(PinnedSku).where(PinnedSku.nm_id == nm_id)
        await self._session.execute(stmt)
        await self._session.flush()
