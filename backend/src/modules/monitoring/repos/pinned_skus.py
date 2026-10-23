"""Data access for globally pinned SKUs ("Pin" flags).

Sole owner of SQL for ``monitoring.pinned_sku`` — services depend on this
repository and never issue queries themselves. Presence of a row means the SKU
is pinned; unpinning deletes the row, so both writes are idempotent.
"""

from __future__ import annotations

import uuid

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.pinned_skus import PinnedSku
from src.modules.monitoring.repos.base import workspace_sku_select


class PinnedSkuRepository:
    """Reads and writes the global pinned-SKU list."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def list_rows(self, *, workspace_id: uuid.UUID) -> list[PinnedSku]:
        """Return the workspace's pinned rows in chip-row order.

        Ordering is the manual ``sort_order`` set by drag-and-drop, falling
        back to pin order (``created_at``, then ``nm_id``) for rows that share
        a position — which is what unreordered pins do, since they all keep
        their insertion positions.

        Args:
            workspace_id: Restrict to SKUs owned by this workspace.

        Returns:
            The pinned rows (empty when nothing is pinned).
        """
        stmt = (
            select(PinnedSku)
            .where(PinnedSku.nm_id.in_(workspace_sku_select(workspace_id)))
            .order_by(PinnedSku.sort_order, PinnedSku.created_at, PinnedSku.nm_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, *, nm_id: int) -> None:
        """Pin a SKU, appending it to the end of the row (no-op when pinned).

        Args:
            nm_id: WB SKU identifier to pin.
        """
        # Append: one past the highest position in the table (0 when empty).
        # The subquery reads the pre-INSERT table, so it cannot see this row.
        next_order = select(func.coalesce(func.max(PinnedSku.sort_order) + 1, 0)).scalar_subquery()
        stmt = (
            pg_insert(PinnedSku)
            .values(nm_id=nm_id, sort_order=next_order)
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

    async def reorder(self, *, nm_ids: list[int]) -> None:
        """Write the given ``nm_id`` sequence as the chip row's positions.

        Positions are assigned densely from 0 in list order. Only the listed
        rows are touched: a workspace reorders its own pins, and the pins of
        other workspaces keep whatever positions they had.

        Args:
            nm_ids: Pinned SKU identifiers in their new left-to-right order.
        """
        if not nm_ids:
            return
        position = case({nm_id: index for index, nm_id in enumerate(nm_ids)}, value=PinnedSku.nm_id)
        stmt = update(PinnedSku).where(PinnedSku.nm_id.in_(nm_ids)).values(sort_order=position)
        await self._session.execute(stmt)
        await self._session.flush()

    async def set_color(self, *, nm_id: int, color: str | None) -> None:
        """Paint a pinned chip, or clear its tint (no-op when not pinned).

        Args:
            nm_id: WB SKU identifier whose chip is painted.
            color: ``#rrggbb`` tint, or ``None`` to reset to the default chip.
        """
        stmt = update(PinnedSku).where(PinnedSku.nm_id == nm_id).values(color=color)
        await self._session.execute(stmt)
        await self._session.flush()
