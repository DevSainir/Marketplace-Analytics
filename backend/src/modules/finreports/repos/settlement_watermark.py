"""Data access for the settlement walk's own high-water mark."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.modules.finreports.models import SettlementWatermark
from src.modules.finreports.repos.base import BaseRepository


class SettlementWatermarkRepository(BaseRepository):
    """Where each workspace's settlement walk has got to."""

    model = SettlementWatermark

    async def get(self, *, workspace_id: uuid.UUID) -> date | None:
        """Return the last day this workspace's walk has completed.

        Args:
            workspace_id: Tenancy scope.

        Returns:
            The watermark, or ``None`` when this workspace has never completed a
            settlement window — which the caller must treat as "never harvested"
            and therefore as a reason to walk, not as a reason to skip.
        """
        stmt = select(SettlementWatermark.settled_through).where(
            SettlementWatermark.workspace_id == workspace_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def advance_to(self, *, workspace_id: uuid.UUID, day: date) -> date:
        """Move the watermark forward to ``day``, never backwards.

        The monotonicity is enforced in SQL rather than by reading first and
        writing after, because two harvests can genuinely overlap: the hourly
        tick holds a lock, but a «Обновить» for one workspace does not wait for
        it, and the loser of that race would otherwise rewind the watermark to
        its own older span and re-open a window that had already been closed.

        Args:
            workspace_id: Tenancy scope.
            day: The last day of the walk's completed prefix.

        Returns:
            The watermark after the write — ``day``, or the existing value when
            that was already further ahead.
        """
        stmt = (
            insert(SettlementWatermark)
            .values(workspace_id=workspace_id, settled_through=day)
            .on_conflict_do_update(
                index_elements=[SettlementWatermark.workspace_id],
                set_={
                    "settled_through": func.greatest(SettlementWatermark.settled_through, day),
                    "updated_at": func.now(),
                },
            )
            .returning(SettlementWatermark.settled_through)
        )
        return (await self._session.execute(stmt)).scalar_one()
