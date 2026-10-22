"""The one way the demo seed writes rows: plain multi-row INSERTs in chunks.

Every table the seed fills is emptied first (see :mod:`scripts.seed_demo.tenancy`),
so nothing here upserts. The rows are dictionaries with identical keys per call,
which is what lets SQLAlchemy send each chunk as a single statement.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import Base

#: Rows per statement. asyncpg caps one statement at 32 767 bind parameters, and
#: the widest table here (the settlement detail) has about seventy columns.
_CHUNK = 400


async def insert_rows(
    session: AsyncSession, model: type[Base], rows: Sequence[dict[str, Any]]
) -> int:
    """Insert ``rows`` into ``model``'s table, returning how many were written."""
    for start in range(0, len(rows), _CHUNK):
        await session.execute(insert(model), list(rows[start : start + _CHUNK]))
    return len(rows)
