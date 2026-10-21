"""Shared repository plumbing for the ``finreports`` module.

An async, idempotent bulk-upsert built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so re-harvesting the same window overwrites
prior values instead of raising primary-key violations — mirrors the monitoring
module's ``BaseRepository`` (kept independent per the no-horizontal-import rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base
from src.core.upsert import upsert_rows


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
        return await upsert_rows(
            self._session,
            self.model,
            rows,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
        )
