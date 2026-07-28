"""Shared repository plumbing for the ``finreports`` module.

An async, idempotent bulk-upsert built on PostgreSQL's
``INSERT ... ON CONFLICT DO UPDATE`` so re-harvesting the same window overwrites
prior values instead of raising primary-key violations — mirrors the monitoring
module's ``BaseRepository`` (kept independent per the no-horizontal-import rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
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

    async def checksum(
        self,
        *columns: Any,
        where: Sequence[Any] = (),
    ) -> tuple[int, int]:
        """Return ``(row count, order-independent checksum)`` for a row set.

        Computed **entirely in PostgreSQL**: the aggregate returns two numbers,
        so nothing is hydrated into Python. That is the whole point — the claim
        package's cache needs to know whether its inputs changed, and building
        83 443 row objects to answer that took 5.5 s while this answers it in
        ~0.2 s (measured on production data).

        ``hashtext`` is applied per row over the concatenated significant
        columns, so the result moves if any one of them moves — including an
        in-place restatement, which a ``max(created_at)`` watermark cannot see
        (the harvest upserts value columns only, and these tables have no
        ``updated_at``). Summing makes it order-independent; ``count`` is
        carried alongside so that additions and removals that happen to offset
        in the sum still change the pair.

        Args:
            *columns: The value columns whose change must invalidate. Cast and
                concatenated in the given order.
            where: Predicate applied to the row set.

        Returns:
            ``(count, checksum)``. ``(0, 0)`` for an empty set.
        """
        parts: list[Any] = []
        for column in columns:
            parts.extend([sa.func.coalesce(sa.cast(column, sa.Text), ""), sa.literal(":")])
        digest = sa.func.coalesce(
            sa.func.sum(sa.cast(sa.func.hashtext(sa.func.concat(*parts)), sa.BigInteger)), 0
        )
        stmt = sa.select(sa.func.count(), digest).select_from(self.model)
        if where:
            stmt = stmt.where(*where)
        count, checksum = (await self._session.execute(stmt)).one()
        return int(count), int(checksum)
