"""A capture run stores what it walks as it walks it, and keeps it when it dies.

The walks stopped returning a whole run on 2026-09-17 — the orders feed's eight
pages of 80 000 rows were what the cgroup OOM killer took the worker for the
night before. They yield batches now, and `capture` writes each one.

That moves the interesting question from memory to transactions: rows land
before the run is over, so the watermark and the rows can disagree, and a
watermark ahead of its rows steps over them permanently. These tests run the
real `_capture_one` against real PostgreSQL — fake WB, real commits — because
the property is about what survives a commit boundary, and a fake session
does not have one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.modules.guide import models
from src.modules.guide.services import capture
from src.modules.guide.services.fetch import CaptureBatch, CaptureWindow
from src.modules.guide.sources import GuideCadence, GuideSource
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
_SOURCE_KEY = "orders"


class _NoClient:
    """Stands in for the WB client, which these walks do not use."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _NoClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _source(walk: Any) -> GuideSource:
    """A catalogue entry wrapping one hand-written walk.

    The host is the documents one deliberately: it is not in `capture`'s table
    of shared gates, so these tests pace against nothing and never reach Redis.
    """
    return GuideSource(
        key=_SOURCE_KEY,
        title="Заказы",
        cadence=GuideCadence.DAILY,
        base_url="wb_documents_base_url",
        tokens=("statistics",),
        fetch=walk,
        why="test",
        retention="test",
    )


def _tokens() -> WorkspaceTokenBundle:
    """A workspace carrying the scope the fake source asks for."""
    return WorkspaceTokenBundle(workspace_id=_WORKSPACE, name="Демо", statistics="stat-token")


@pytest.fixture
def wb(monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Point the capture at the test transaction and away from WB."""
    monkeypatch.setattr(capture, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(capture, "WBReferenceClient", _NoClient)


async def _stored(session: AsyncSession) -> list[str]:
    """Record keys this source has stored for this workspace, in order."""
    result = await session.execute(
        sa.select(models.GuideRecord.record_key)
        .where(models.GuideRecord.source == _SOURCE_KEY)
        .where(models.GuideRecord.workspace_id == _WORKSPACE)
        .order_by(models.GuideRecord.record_key)
    )
    return [str(key) for key in result.scalars().all()]


async def _run(session: AsyncSession) -> models.GuideRun:
    """The watermark row this source left behind."""
    result = await session.execute(
        sa.select(models.GuideRun)
        .where(models.GuideRun.source == _SOURCE_KEY)
        .where(models.GuideRun.workspace_id == _WORKSPACE)
    )
    return result.scalar_one()


def _batch(key: str, *, cursor: str | None = None) -> CaptureBatch:
    """One row's worth of batch, optionally carrying a resume point."""
    return CaptureBatch(rows=[(key, None, {"srid": key})], cursor=cursor)


async def test_a_walk_that_dies_keeps_every_batch_it_had_already_stored(
    wb: None, db_session: AsyncSession
) -> None:
    """The rows are in the database; throwing them away would buy nothing.

    WB serves this feed 80 000 rows at a time and the walk stores them in
    slices, so by the time a body fails mid-stream a first run may have written
    a hundred megabytes of them. Re-reading all of it next run costs a WB budget
    that is shared with the harvests that earn money.
    """

    async def walk(_client: Any, _window: CaptureWindow) -> AsyncIterator[CaptureBatch]:
        yield _batch("a", cursor="2026-09-11T10:00:00")
        yield _batch("b")
        raise IntegrationError("WB closed the body half-way.")

    status, rows, _message = await capture._capture_one(_source(walk), _tokens(), config=settings)

    assert (status, rows) == ("failed", 2)
    assert await _stored(db_session) == ["a", "b"]


async def test_a_dead_walks_watermark_stops_at_the_last_batch_that_named_one(
    wb: None, db_session: AsyncSession
) -> None:
    """The one direction that is not recoverable, pinned.

    Rows stored without a watermark are re-read — wasteful and harmless. A
    watermark past rows that were never stored skips them for ever, and nothing
    downstream can tell. So the walk's LAST safe point wins, not its last batch:
    here the second batch deliberately carries no cursor, because its feed could
    not name one that was safe to resume from mid-page.
    """

    async def walk(_client: Any, _window: CaptureWindow) -> AsyncIterator[CaptureBatch]:
        yield _batch("a", cursor="2026-09-11T10:00:00")
        yield _batch("b")
        raise IntegrationError("WB closed the body half-way.")

    await capture._capture_one(_source(walk), _tokens(), config=settings)

    run = await _run(db_session)
    assert run.cursor == "2026-09-11T10:00:00"
    assert run.last_status == "failed"


async def test_a_walk_that_finishes_records_its_last_cursor_and_row_count(
    wb: None, db_session: AsyncSession
) -> None:
    """The ordinary path: everything stored, the newest resume point kept."""

    async def walk(_client: Any, _window: CaptureWindow) -> AsyncIterator[CaptureBatch]:
        yield _batch("a", cursor="2026-09-11T10:00:00")
        yield _batch("b", cursor="2026-09-11T23:40:00")

    status, rows, _message = await capture._capture_one(_source(walk), _tokens(), config=settings)

    run = await _run(db_session)
    assert (status, rows) == ("ok", 2)
    assert (run.cursor, run.rows, run.last_status) == ("2026-09-11T23:40:00", 2, "ok")


async def test_a_feed_that_cannot_be_stored_fails_alone(
    wb: None, db_session: AsyncSession
) -> None:
    """One bad feed must not cost the other ten their run — storage errors too.

    The module has promised this since it was written, and the promise held only
    while fetching and storing were separate phases: a parse error raised from
    the fetch, and the four exception types caught here covered it. A walk that
    writes as it goes raises from the INSERT instead, and a `StatementError` is
    none of those four.

    On 2026-09-17 that difference escaped `_capture_one`, killed the whole
    `guide.capture_daily` task, and the feeds after it in the cadence never ran —
    because ijson hands back `Decimal` and a JSONB column will not take one.
    """

    async def walk(_client: Any, _window: CaptureWindow) -> AsyncIterator[CaptureBatch]:
        yield CaptureBatch(rows=[("a", None, {"price": Decimal("1.5")})])

    status, rows, message = await capture._capture_one(
        _source(walk), _tokens(), config=settings
    )

    assert (status, rows) == ("failed", 0)
    assert "Decimal" in message
