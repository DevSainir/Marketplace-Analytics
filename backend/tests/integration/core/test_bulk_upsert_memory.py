"""A bulk upsert leaves the database connection no heavier than it found it.

Every bulk write was a multi-row ``INSERT … VALUES`` chunked to asyncpg's bind
limit, and asyncpg caches every statement it prepares — so the SERVER kept the
plan of each batch size for the life of the connection, ~12 MB apiece for the
63-column settlement detail. Three sellers harvested at once put three such
backends into the 384 MiB postgres container and the kernel killed one: on
2026-09-24, 09-28, and 09-29 in the middle of the nightly pg_dump.

The measurement is the backend's own ``RssAnon``, read from ``/proc/self/status``
through ``pg_read_file`` — the figure the kernel's OOM report named.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.repos import LogisticsTransactionRepository
from src.modules.finreports.services.ingestion.columns import TXN_UPDATE

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000b0b0")

#: The settlement pages differ in length, so their tail batches do too.
BATCH_SIZES = (2000, 1300, 777)


def _value(column: sa.ColumnElement[Any], index: int) -> object:
    """A plausible value for any settlement column, so a row is as wide as WB's."""
    kind = column.type
    if column.name == "workspace_id":
        return WORKSPACE
    if column.name == "rrd_id":
        return 7_000_000_000 + index
    if isinstance(kind, sa.Uuid):
        return uuid.uuid4()
    if isinstance(kind, sa.Integer):
        return index % 1000
    if isinstance(kind, sa.Numeric):
        return Decimal("12.34")
    if isinstance(kind, sa.DateTime):
        return datetime(2026, 9, 1, tzinfo=UTC)
    if isinstance(kind, sa.Date):
        return date(2026, 9, 1 + index % 20)
    if isinstance(kind, sa.Boolean):
        return False
    return "x"


def _rows(count: int, first: int) -> list[dict[str, object]]:
    """``count`` full-width settlement rows with distinct ``rrd_id``."""
    columns = [c for c in LogisticsTransaction.__table__.columns if c.server_default is None]
    return [{c.name: _value(c, first + i) for c in columns} for i in range(count)]


async def _backend_anon_mb(session: AsyncSession) -> int:
    status = await session.scalar(sa.text("SELECT pg_read_file('/proc/self/status')"))
    line = next(line for line in str(status).splitlines() if line.startswith("RssAnon:"))
    return int(line.split()[1]) // 1024


async def test_batches_of_different_sizes_leave_no_memory_on_the_connection(
    db_session: AsyncSession,
) -> None:
    """Three batch sizes of the settlement detail cost the backend under 10 MB, kept or not.

    The multi-row form left 57 MB on this connection for the same three batches,
    through the end of the statements — memory only closing the connection frees.
    """
    repo = LogisticsTransactionRepository(db_session)
    before = await _backend_anon_mb(db_session)
    first = 0
    for size in BATCH_SIZES:
        await repo.bulk_upsert(
            _rows(size, first), conflict_columns=["rrd_id"], update_columns=TXN_UPDATE
        )
        first += size

    after = await _backend_anon_mb(db_session)

    stored = await db_session.scalar(
        sa.select(sa.func.count()).where(LogisticsTransaction.workspace_id == WORKSPACE)
    )
    assert stored == sum(BATCH_SIZES)
    assert after - before < 10, f"the connection kept {after - before} MB after the upserts"
