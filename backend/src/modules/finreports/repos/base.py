"""Shared repository plumbing for the ``finreports`` module.

An async, idempotent bulk-upsert built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so re-harvesting the same window overwrites
prior values instead of raising primary-key violations — mirrors the monitoring
module's ``BaseRepository`` (kept independent per the no-horizontal-import rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base

#: asyncpg's Bind message counts parameters in an int16 → 32767 ceiling. Chunk
#: so N rows x C columns stays under it with headroom.
_MAX_BIND_PARAMS = 30000


class BaseRepository:
    """Common async persistence helpers for finreports repositories."""

    #: ORM model this repository manages. Subclasses must override.
    model: type[Base]

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def bulk_upsert(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        """Insert rows, updating the given columns on primary-key conflict.

        Args:
            rows: Column->value mappings to persist (empty is a no-op → ``0``).
            conflict_columns: Columns forming the conflict target (PK / unique).
            update_columns: Columns overwritten with incoming values on conflict.

        Returns:
            The number of rows submitted for upsert.
        """
        if not rows:
            return 0
        columns_per_row = max((len(row) for row in rows), default=1)
        chunk_size = max(1, _MAX_BIND_PARAMS // columns_per_row)
        rows_list = list(rows)
        for start in range(0, len(rows_list), chunk_size):
            chunk = rows_list[start : start + chunk_size]
            stmt = pg_insert(self.model).values(chunk)
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=list(conflict_columns),
                set_={column: excluded[column] for column in update_columns},
            )
            await self._session.execute(stmt)
        return len(rows_list)
