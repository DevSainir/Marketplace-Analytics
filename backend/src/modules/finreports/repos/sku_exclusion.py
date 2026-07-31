"""Data access for the per-SKU «Не включать в общий счёт» marks."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.modules.finreports.models import PnlSkuExclusion
from src.modules.finreports.repos.base import BaseRepository


class SkuExclusionRepository(BaseRepository):
    """The seller's «Не включать в общий счёт» marks, keyed ``(workspace_id, nm_id)``."""

    model = PnlSkuExclusion

    async def excluded_nm_ids(self, workspace_id: uuid.UUID) -> set[int]:
        """Return the SKUs currently marked for a workspace.

        Args:
            workspace_id: Owning workspace.

        Returns:
            The set of marked ``nm_id``s (empty when none are marked).
        """
        stmt = select(PnlSkuExclusion.nm_id).where(PnlSkuExclusion.workspace_id == workspace_id)
        return {int(nm_id) for nm_id in (await self._session.execute(stmt)).scalars().all()}

    async def set_excluded(self, *, workspace_id: uuid.UUID, nm_id: int, excluded: bool) -> None:
        """Mark or unmark one SKU.

        Idempotent both ways: marking an already-marked SKU is a no-op insert
        (``ON CONFLICT DO NOTHING``), and unmarking an absent one deletes nothing.

        Args:
            workspace_id: Owning workspace.
            nm_id: SKU the mark applies to.
            excluded: ``True`` to mark «Не включать», ``False`` to clear it.
        """
        if excluded:
            stmt = (
                pg_insert(PnlSkuExclusion)
                .values(workspace_id=workspace_id, nm_id=nm_id)
                .on_conflict_do_nothing(index_elements=["workspace_id", "nm_id"])
            )
            await self._session.execute(stmt)
            return
        await self._session.execute(
            delete(PnlSkuExclusion).where(
                PnlSkuExclusion.workspace_id == workspace_id,
                PnlSkuExclusion.nm_id == nm_id,
            )
        )
