"""Repository for :class:`MatrixOverride` rows (manual matrix edits)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import MatrixOverride
from src.modules.monitoring.repos.base import BaseRepository


class MatrixOverrideRepository(BaseRepository):
    """CRUD/read operations for manual metrics-matrix overrides."""

    model = MatrixOverride

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def list_for_sku(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[MatrixOverride]:
        """Return a SKU's overrides whose day falls in the inclusive window.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            The matching override rows (empty when the SKU has no edits).
        """
        stmt = select(MatrixOverride).where(
            MatrixOverride.nm_id == nm_id,
            MatrixOverride.stat_date >= date_from,
            MatrixOverride.stat_date <= date_to,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def replace_window(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        rows: list[dict[str, object]],
    ) -> int:
        """Replace a SKU's overrides for a window with a fresh set.

        Deletes every override for the SKU inside the window first (so a cell
        edited back to its harvested value drops its row), then inserts ``rows``
        — all in the caller's transaction.

        Args:
            nm_id: WB SKU identifier.
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            rows: Column->value mappings for the overrides to persist.

        Returns:
            The number of override rows inserted.
        """
        await self._session.execute(
            delete(MatrixOverride).where(
                MatrixOverride.nm_id == nm_id,
                MatrixOverride.stat_date >= date_from,
                MatrixOverride.stat_date <= date_to,
            )
        )
        if rows:
            self._session.add_all([MatrixOverride(**row) for row in rows])
        # The session runs with autoflush disabled, so flush now — the save path
        # re-reads these overrides in the same transaction (to return the
        # refreshed detail) before the request-level commit.
        await self._session.flush()
        return len(rows)

    async def delete_for_skus(self, nm_ids: Iterable[int]) -> int:
        """Delete all overrides for the given SKUs (a WB refresh clears edits).

        Args:
            nm_ids: SKU ids whose overrides should be cleared.

        Returns:
            The number of override rows deleted.
        """
        ids = list(nm_ids)
        if not ids:
            return 0
        stmt = delete(MatrixOverride).where(MatrixOverride.nm_id.in_(ids))
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)
