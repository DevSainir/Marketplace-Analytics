"""Data access for pinned search phrases («Закрепить» on the position box).

Sole owner of SQL for ``monitoring.pinned_keyword`` — services depend on this
repository and never issue queries themselves. Pinning upserts, unpinning
deletes, so both writes are idempotent and a double-click cannot fail.

Every read is scoped through ``workspace_sku_select``: the table itself carries
no workspace column (``nm_id`` already belongs to exactly one workspace), so the
semijoin IS the tenancy boundary here, not a convenience.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models.pinned_keywords import PinnedKeyword
from src.modules.monitoring.repos.base import workspace_sku_select


class PinnedKeywordRepository:
    """Reads and writes pinned search phrases and their latest positions."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def list_for_sku(self, *, nm_id: int) -> list[PinnedKeyword]:
        """Return one SKU's pins, oldest first.

        Pin order is creation order: the cards are a list the seller built, and
        reordering them on every refresh would lose the only ordering they have.

        Args:
            nm_id: The SKU whose pins to read (ownership proven by the caller).

        Returns:
            The SKU's pinned phrases (empty when none are pinned).
        """
        stmt = (
            select(PinnedKeyword)
            .where(PinnedKeyword.nm_id == nm_id)
            .order_by(PinnedKeyword.created_at, PinnedKeyword.keyword)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_workspace(self, *, workspace_id: uuid.UUID) -> list[PinnedKeyword]:
        """Return every pin belonging to one workspace's SKUs.

        The refresh task's input. Scoped through the SKU registry, so a pin left
        behind by a SKU that changed hands cannot be probed on the new owner's
        rate budget.

        Args:
            workspace_id: The workspace whose pins to read.

        Returns:
            Every pinned phrase across the workspace's catalogue.
        """
        stmt = (
            select(PinnedKeyword)
            .where(PinnedKeyword.nm_id.in_(workspace_sku_select(workspace_id)))
            .order_by(PinnedKeyword.nm_id, PinnedKeyword.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def pin(self, *, nm_id: int, keyword: str) -> PinnedKeyword:
        """Pin a phrase to a SKU, or return the existing pin unchanged.

        Deliberately does NOT reset the stored result on a re-pin: the phrase is
        the identity, and re-adding one already on the board must not blank the
        number the seller is watching.

        Args:
            nm_id: The SKU to pin the phrase to.
            keyword: The phrase as typed.

        Returns:
            The pinned row, freshly created or already present.
        """
        stmt = (
            pg_insert(PinnedKeyword)
            .values(nm_id=nm_id, keyword=keyword)
            .on_conflict_do_update(
                index_elements=[PinnedKeyword.nm_id, PinnedKeyword.keyword],
                # A no-op write to its own key: the row is returned on both the
                # insert and the conflict path, which DO NOTHING cannot do (it
                # returns nothing at all when the pin already exists).
                set_={"nm_id": nm_id},
            )
            .returning(PinnedKeyword)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def unpin(self, *, nm_id: int, keyword: str) -> int:
        """Remove a pin.

        Args:
            nm_id: The SKU the phrase is pinned to.
            keyword: The phrase to unpin.

        Returns:
            The number of rows deleted (0 when it was not pinned).
        """
        stmt = delete(PinnedKeyword).where(
            PinnedKeyword.nm_id == nm_id, PinnedKeyword.keyword == keyword
        )
        # A DML statement always yields a CursorResult; the base Result type does
        # not declare rowcount, so the narrowing is stated rather than ignored.
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return int(result.rowcount or 0)

    async def record_probe(
        self,
        *,
        nm_id: int,
        keyword: str,
        normalized_query: str,
        position: int | None,
        positions_scanned: int,
        total_found: int,
        truncated: bool,
        checked_at: datetime,
    ) -> None:
        """Store the outcome of one probe against one pin.

        Writes only to pins that exist: a phrase unpinned while the refresh was
        running must not be resurrected by its own result landing late.

        Args:
            nm_id: The SKU the phrase is pinned to.
            keyword: The pinned phrase.
            normalized_query: WB's normalization of it.
            position: The rank found, or ``None`` when outside the scanned depth.
            positions_scanned: How deep the scan looked.
            total_found: WB's result count for the phrase.
            truncated: Whether results existed deeper than the scan reached.
            checked_at: When the probe ran.
        """
        stmt = (
            update(PinnedKeyword)
            .where(PinnedKeyword.nm_id == nm_id, PinnedKeyword.keyword == keyword)
            .values(
                normalized_query=normalized_query,
                last_position=position,
                last_positions_scanned=positions_scanned,
                last_total_found=total_found,
                last_truncated=truncated,
                last_checked_at=checked_at,
            )
        )
        await self._session.execute(stmt)
