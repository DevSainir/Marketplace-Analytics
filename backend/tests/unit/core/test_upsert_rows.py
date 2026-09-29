"""A bulk upsert refuses rows that do not all carry the same columns."""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.upsert import upsert_rows
from src.modules.guide.models import GuideRecord

pytestmark = pytest.mark.unit


class _SessionThatMustNotBeUsed:
    """Stands in for a session the helper should never reach."""

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("the rows reached the database")


async def test_a_column_missing_from_the_first_row_is_refused_not_dropped() -> None:
    """The later row's extra column would be silently written as NULL otherwise.

    ``executemany`` compiles one statement from the first row's keys, so a key
    only later rows carry is left out of every row — measured: the second row's
    value came back NULL, with no error.
    """
    session = cast(AsyncSession, _SessionThatMustNotBeUsed())
    rows: list[dict[str, Any]] = [
        {"source": "orders", "record_key": "a"},
        {"source": "orders", "record_key": "b", "payload": {"x": 1}},
    ]

    with pytest.raises(ValueError, match="same columns"):
        await upsert_rows(
            session,
            GuideRecord,
            rows,
            conflict_columns=["source", "record_key"],
            update_columns=["payload"],
        )
