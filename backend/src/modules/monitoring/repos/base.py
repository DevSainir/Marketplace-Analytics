"""Shared repository plumbing for the Monitoring module.

Provides an async, idempotent bulk-upsert helper built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so that re-harvesting the same window
overwrites prior values instead of raising primary-key violations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base


class BaseRepository:
    """Common async persistence helpers shared by monitoring repositories."""

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
            rows: Column->value mappings to persist. An empty sequence is a
                no-op that returns ``0``.
            conflict_columns: Columns forming the conflict target (the primary
                key / unique index).
            update_columns: Columns to overwrite with the incoming values when a
                conflicting row already exists.

        Returns:
            The number of rows submitted for upsert.
        """
        if not rows:
            return 0

        stmt = pg_insert(self.model).values(list(rows))
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_columns),
            set_={column: excluded[column] for column in update_columns},
        )
        await self._session.execute(stmt)
        return len(rows)
