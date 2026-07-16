"""Shared repository plumbing for the Monitoring module.

Provides an async, idempotent bulk-upsert helper built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so that re-harvesting the same window
overwrites prior values instead of raising primary-key violations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base
from src.modules.monitoring.models import ProductCard

#: The binding-count ceiling for ONE statement is asyncpg's 32767 (the wire
#: protocol's Bind message counts parameters in an int16), NOT PostgreSQL's
#: often-quoted 65535. A batch of N rows with C columns sends N*C params, so a
#: big ingest (a ~10k-record sales pull, or a 31-day advertising backfill
#: window — observed live: 51520 params → asyncpg error) overflows one INSERT.
#: Chunk so each statement stays under the limit, with headroom.
_MAX_BIND_PARAMS = 30000


def workspace_sku_select(workspace_id: uuid.UUID) -> Select[tuple[int]]:
    """Build the ``nm_id`` semijoin restricting a query to one workspace's SKUs.

    ``product_card`` is the authoritative SKU -> workspace registry (see
    :class:`~src.modules.monitoring.models.products.ProductCard`). Every
    cross-SKU aggregate uses this as an ``IN`` subquery so SKUs of other
    workspaces — or unclaimed legacy rows — never surface.

    Args:
        workspace_id: The active workspace.

    Returns:
        A ``SELECT nm_id FROM product_card WHERE workspace_id = :ws`` statement
        suitable for ``Column.in_()``.
    """
    return select(ProductCard.nm_id).where(ProductCard.workspace_id == workspace_id)


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

        Large batches are split into multiple statements so the per-statement
        bind-parameter cap (65535) is never exceeded — a single harvest can
        carry tens of thousands of rows.

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

        # Chunk by row count so each statement stays under the param cap
        # (columns-per-row = len of the widest row mapping; >= 1).
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
