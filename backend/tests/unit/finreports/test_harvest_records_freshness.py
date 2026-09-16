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
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.harvest import fleet, harvest_all_workspaces
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-0000000000f1")
SETTLED = date(2026, 9, 6)


class _FakeRedis:
    """The lock commands plus the two the record uses, all in memory."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        #: Every value written to the freshness key, in order. The run records
        #: twice — before the branch and again from the walk — and which came
        #: first is a property in its own right.
        self.freshness_writes: list[str] = []

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
        if key == freshness_key(WORKSPACE):
            self.freshness_writes.append(value)
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


class _FakeReportRepo:
    """Reports the settlement coverage the walk left behind."""

    #: Rebound per test — what ``latest_settled_date`` answers after the walk.
    settled_after: date | None = SETTLED

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        return _FakeReportRepo.settled_after


def _bundle() -> WorkspaceTokenBundle:
    """One workspace with a usable statistics token."""
    return WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", statistics="stat-token")


@pytest.fixture(autouse=True)
def _settled_after_the_walk() -> Any:
    """Default: the walk moved nothing, which is the ordinary quiet week."""
    _FakeReportRepo.settled_after = SETTLED
    yield
    _FakeReportRepo.settled_after = SETTLED


@pytest.fixture
def redis_and_walk(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire a fleet of one, with the DB, the clock and the walk replaced.

    Returns a callable taking the Redis to run against and the verdict the gate
    should reach, and giving back ``(redis, walked)``.
    """

    def _run(
        redis: _FakeRedis,
        verdict: FreshnessVerdict,
        walk_counts: dict[str, int] | None = None,
    ) -> tuple[_FakeRedis, list[uuid.UUID]]:
        walked: list[uuid.UUID] = []
        counts = {"finance_windows_failed": 0} if walk_counts is None else walk_counts

        async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
            return [_bundle()]

        async def _check(**_kwargs: object) -> FreshnessVerdict:
            return verdict

        async def _walk(*, tokens: WorkspaceTokenBundle, **_kwargs: object) -> dict[str, int]:
            walked.append(tokens.workspace_id)
            return counts

        # The lock lives in `harvest`; the freshness record and the walk's own
        # verdict live in `freshness`. Both reach Redis through `get_redis`.
        monkeypatch.setattr(fleet, "get_redis", lambda: redis)
        monkeypatch.setattr(freshness, "get_redis", lambda: redis)
        monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
        monkeypatch.setattr(freshness, "AsyncSessionLocal", _FakeSession)
        monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
        # The loop reads BOTH — the frontier is the earlier of them. See
        # `tests/unit/finreports/test_settlement_frontier.py` for why.
        monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
        monkeypatch.setattr(freshness, "FinancialReportRepository", _FakeReportRepo)
        monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
        monkeypatch.setattr(fleet, "check_freshness", _check)
        monkeypatch.setattr(fleet, "harvest_workspace", _walk)

        # The gap survey runs on every tick now, and it opens its own session:
        # left real, these unit tests would reach a database. What it finds is
        # not this file's subject — see `test_settlement_reconciliation.py`.
        async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
            return {}

        monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
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
    _FakeReportRepo.settled_after = date(2026, 9, 13)
    redis, walked = redis_and_walk(_FakeRedis(), verdict)

    await harvest_all_workspaces(days=28)

    stored = _stored(redis)
    assert walked == [WORKSPACE]
    assert stored is not None
    assert stored.outcome is FreshnessOutcome.WB_HAS_NEW


async def test_a_failed_probe_is_recorded_as_a_failure_and_still_harvests(
    redis_and_walk: Any,
) -> None:
    """WB not answering may never be stored as «нового ничего нет».

    Recorded at the moment of the branch, before the walk it fails open into has
    proved anything. If a failed probe went down as an empty answer the page
    would report silence as reassurance — the exact failure this feature exists
    to prevent — and a harvest that then died would leave that reassurance
    standing.
    """
    verdict = FreshnessVerdict(
        outcome=FreshnessOutcome.PROBE_FAILED,
        checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
        probe_from=date(2026, 9, 7),
        probe_to=date(2026, 9, 8),
    )
    redis, walked = redis_and_walk(_FakeRedis(), verdict)

    await harvest_all_workspaces(days=28)

    first = FreshnessVerdict.from_json(json.loads(redis.freshness_writes[0]))
    assert first is not None
    assert first.outcome is FreshnessOutcome.PROBE_FAILED
    assert walked == [WORKSPACE]


async def test_a_completed_walk_supersedes_the_failed_probe_that_let_it_run(
    redis_and_walk: Any,
) -> None:
    """The walk asked the same days and got an answer — the probe's silence is stale.

    Prod, 2026-09-09: the probe hit the settlement endpoint's 15-minute block
    and 429'd, the gate failed open, and seven minutes later the walk asked the
    same window and got 204 — proof there was nothing new. Left at
    `probe_failed` the page warns «данные могут быть неполными» over a statement
    that has just been confirmed complete, until the next tick happens to
    succeed.
    """
    redis, walked = redis_and_walk(
        _FakeRedis(),
        FreshnessVerdict(
            outcome=FreshnessOutcome.PROBE_FAILED,
            checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
            probe_from=date(2026, 9, 7),
            probe_to=date(2026, 9, 8),
        ),
    )

    await harvest_all_workspaces(days=28)

    stored = _stored(redis)
    assert walked == [WORKSPACE]
    assert stored is not None
    assert stored.outcome is FreshnessOutcome.WB_EMPTY


async def test_a_walk_that_lost_a_window_leaves_the_failure_standing(
    redis_and_walk: Any,
) -> None:
    """A partly-failed walk proves nothing, so it may not overwrite a warning.

    This is the direction that must never be got wrong: upgrading an incomplete
    walk to «нового ничего нет» would report a gap in the data as reassurance —
    the same failure as narrating a failed probe that way.
    """
    redis, _ = redis_and_walk(
        _FakeRedis(),
        FreshnessVerdict(
            outcome=FreshnessOutcome.PROBE_FAILED,
            checked_at=datetime(2026, 9, 9, 6, 14, tzinfo=UTC),
        ),
        {"finance_windows_failed": 1},
    )

    await harvest_all_workspaces(days=28)

    stored = _stored(redis)
    assert stored is not None
    assert stored.outcome is FreshnessOutcome.PROBE_FAILED


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
