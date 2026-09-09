"""Every tick leaves a trace, including the ticks that decide to do nothing.

This is the bug the freshness line closes, pinned at its source. The gate has
always reached a verdict and thrown it away, so a workspace WB published nothing
for and a workspace whose harvester died produced the same evidence: no rows, no
new report, nothing recorded. In August 2026 that cost three days.

So the verdict is recorded **before** the branch. If only the harvesting path
recorded, "asked WB and there was nothing" would still be invisible — which is
the quiet week the dead worker is hiding behind. And because this record is a
footnote on the harvest, not a part of it, a Redis outage must never reach the
walk it annotates.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from redis.exceptions import RedisError

from src.modules.finreports.constants import HARVEST_LOCK_KEY
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
    freshness_key,
)
from src.modules.finreports.tasks import harvest
from src.modules.finreports.tasks.harvest import harvest_all_workspaces
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-0000000000f1")
SETTLED = date(2026, 9, 6)


class _FakeRedis:
    """The lock commands plus the two the record uses, all in memory."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        key, token = args[0], args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _BrokenWriteRedis(_FakeRedis):
    """A Redis that takes the lock but cannot store the freshness record.

    Deliberately partial: the outage has to hit the footnote while the harvest
    itself is still able to run, or the test proves nothing about which of the
    two survives.
    """

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        if key == freshness_key(WORKSPACE):
            raise RedisError("connection refused")
        return await super().set(key, value, nx=nx, px=px, ex=ex)


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    """Reports one settled day for every workspace."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SETTLED


def _bundle() -> WorkspaceTokenBundle:
    """One workspace with a usable statistics token."""
    return WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", statistics="stat-token")


@pytest.fixture
def redis_and_walk(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire a fleet of one, with the DB, the clock and the walk replaced.

    Returns a callable taking the Redis to run against and the verdict the gate
    should reach, and giving back ``(redis, walked)``.
    """

    def _run(redis: _FakeRedis, verdict: FreshnessVerdict) -> tuple[_FakeRedis, list[uuid.UUID]]:
        walked: list[uuid.UUID] = []

        async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
            return [_bundle()]

        async def _check(**_kwargs: object) -> FreshnessVerdict:
            return verdict

        async def _walk(*, tokens: WorkspaceTokenBundle, **_kwargs: object) -> dict[str, int]:
            walked.append(tokens.workspace_id)
            return {}

        monkeypatch.setattr(harvest, "get_redis", lambda: redis)
        monkeypatch.setattr(harvest, "AsyncSessionLocal", _FakeSession)
        monkeypatch.setattr(harvest, "SettlementWatermarkRepository", _FakeWatermarkRepo)
        monkeypatch.setattr(harvest, "load_workspace_token_bundles", _bundles)
        monkeypatch.setattr(harvest, "check_freshness", _check)
        monkeypatch.setattr(harvest, "harvest_workspace", _walk)
        return redis, walked

    return _run


def _stored(redis: _FakeRedis) -> FreshnessVerdict | None:
    """The verdict the run left behind, as the API would read it back."""
    raw = redis.store.get(freshness_key(WORKSPACE))
    return FreshnessVerdict.from_json(json.loads(raw)) if raw else None


async def test_a_tick_that_finds_nothing_new_still_records_that_it_asked(
    redis_and_walk: Any,
) -> None:
    """The quiet week's trace — the whole point of recording before the branch.

    Without it the page can only say "the figures stop at last Sunday", which is
    what a healthy quiet week and a three-day-dead harvester both look like.
    """
    checked_at = datetime(2026, 9, 9, 6, 14, tzinfo=UTC)
    verdict = FreshnessVerdict(
        outcome=FreshnessOutcome.WB_EMPTY,
        checked_at=checked_at,
        probe_from=date(2026, 9, 7),
        probe_to=date(2026, 9, 8),
    )
    redis, walked = redis_and_walk(_FakeRedis(), verdict)

    totals = await harvest_all_workspaces(days=28)

    assert walked == []
    assert totals["workspaces_skipped"] == 1
    assert _stored(redis) == verdict


async def test_a_tick_that_harvests_records_the_same_way(redis_and_walk: Any) -> None:
    """Both branches leave a trace, or the traces cannot be compared over time."""
    verdict = FreshnessVerdict(
        outcome=FreshnessOutcome.WB_HAS_NEW,
        checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
        probe_from=date(2026, 9, 7),
        probe_to=date(2026, 9, 8),
    )
    redis, walked = redis_and_walk(_FakeRedis(), verdict)

    await harvest_all_workspaces(days=28)

    assert walked == [WORKSPACE]
    assert _stored(redis) == verdict


async def test_a_failed_probe_is_recorded_as_a_failure_and_still_harvests(
    redis_and_walk: Any,
) -> None:
    """WB not answering may never be stored as «нового ничего нет».

    The stored outcome is what the page reads; if a failed probe were recorded
    as an empty answer, the page would report silence as reassurance — the exact
    failure this feature exists to prevent.
    """
    verdict = FreshnessVerdict(
        outcome=FreshnessOutcome.PROBE_FAILED,
        checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
        probe_from=date(2026, 9, 7),
        probe_to=date(2026, 9, 8),
    )
    redis, walked = redis_and_walk(_FakeRedis(), verdict)

    await harvest_all_workspaces(days=28)

    stored = _stored(redis)
    assert stored is not None
    assert stored.outcome is FreshnessOutcome.PROBE_FAILED
    assert walked == [WORKSPACE]


async def test_a_redis_outage_does_not_reach_the_harvest_it_annotates(
    redis_and_walk: Any,
) -> None:
    """The footnote may not take down the statement.

    A harvest that raised because its freshness record could not be written
    would turn a cache outage into a missing settlement week — inventing the
    failure the line was added to reveal.
    """
    verdict = FreshnessVerdict(
        outcome=FreshnessOutcome.WB_HAS_NEW,
        checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
    )
    redis, walked = redis_and_walk(_BrokenWriteRedis(), verdict)

    totals = await harvest_all_workspaces(days=28)

    assert walked == [WORKSPACE]
    assert totals["skipped_locked"] == 0
    assert freshness_key(WORKSPACE) not in redis.store
    assert HARVEST_LOCK_KEY not in redis.store
