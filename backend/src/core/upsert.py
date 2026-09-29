"""One upsert statement, executed once per row, for every bulk write in the app.

Every bulk write used to be a multi-row ``INSERT … VALUES (…), (…) … ON CONFLICT``
chunked to asyncpg's 32767 bind parameters — for the settlement detail that is
~476 rows x 63 columns in one statement. asyncpg prepares and caches every
statement it sends, so the SERVER keeps the parsed plan of each one for as long
as the connection lives, and the batch size makes each of them a new statement:
every page's tail chunk is a different row count. Measured on PostgreSQL 16, one
connection retained 25 MB after one such statement and 58 MB after four sizes,
through a rollback. Three sellers harvested at once made three such backends,
which is what took the 384 MiB postgres container over its limit on 2026-09-24,
09-28 and 09-29 — the last one mid-backup.

Here the statement is one row wide and does not change with the batch: SQLAlchemy
hands the rows to asyncpg's ``executemany``, which pipelines them through the one
prepared statement. The same measurement stays at 2 MB, and the 2000-row batch
that took 1.5 s takes 0.18 s.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base


async def upsert_rows(
    session: AsyncSession,
    model: type[Base],
    rows: Sequence[Mapping[str, Any]],
    *,
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
    also_set: Mapping[str, Any] | None = None,
) -> int:
    """Insert ``rows``, overwriting ``update_columns`` where the conflict key exists.

    Every row must carry the same keys. ``executemany`` compiles the statement from
    the first row, so a key the first row lacks would be dropped from every other
    row without a word — refused here instead, as the multi-row form refused it.

    Two rows with the same conflict key are applied in order, the later winning;
    the multi-row form rejected the whole batch for that instead.

    Args:
        session: The caller's session; the caller owns the transaction.
        model: The target model. Keys are its column names.
        rows: One column->value mapping per row. Plain values only.
        conflict_columns: The primary key or unique index to conflict on.
        update_columns: Columns overwritten from the incoming row on conflict.
        also_set: Extra ``SET`` expressions on conflict, e.g. ``func.now()``.

    Returns:
        The number of rows submitted.

    Raises:
        ValueError: When the rows do not all carry the same keys.
    """
    if not rows:
        return 0
    table = cast(Table, model.__table__)
    keys = rows[0].keys()
    for index, row in enumerate(rows):
        if row.keys() != keys:
            raise ValueError(
                f"upsert into {table.fullname}: row {index} has keys {sorted(row)}, "
                f"row 0 has {sorted(keys)} — every row must carry the same columns."
            )
    statement = pg_insert(table)
    statement = statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_={column: statement.excluded[column] for column in update_columns}
        | dict(also_set or {}),
    )
    await session.execute(statement, list(rows))
    return len(rows)
