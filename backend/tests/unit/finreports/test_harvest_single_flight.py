"""The finance harvest refuses to run alongside itself.

The schedule ticks hourly; a tick that finds a new report walks for minutes of
paced requests. Those two facts only coexist because the walk holds a lock —
otherwise the 10:00 tick would join the 09:00 tick already in flight and the
two would spend each other's budget on a ~1 req/min surface, and both walks
would come back short.

The turned-away tick must be *cheap and silent*: no WB call, no DB session, and
a result whose shape is the same as a real run's so nothing downstream has to
special-case it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from src.modules.finreports.constants import HARVEST_LOCK_KEY
from src.modules.finreports.repos import LatestReportHeader
from src.modules.finreports.services import HarvestControlService
from src.modules.finreports.services.freshness_record import NullFreshnessRecordStore
from src.modules.finreports.tasks.harvest import fleet, harvest_all_workspaces
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


class _HeldRedis:
    """A Redis whose lock key is already taken by another run."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {HARVEST_LOCK_KEY: "another-runs-token"}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
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


async def test_a_tick_that_finds_the_lock_held_does_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arrange a held lock; the tick must return without loading a workspace.

    ``load_workspace_token_bundles`` is the harvest's first act and its first DB
    hit, so replacing it with a detonator proves the run stopped at the lock
    rather than somewhere later.
    """
    redis = _HeldRedis()
    monkeypatch.setattr(fleet, "get_redis", lambda: redis)

    async def _explode(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("the locked-out tick opened a session anyway")

    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _explode)

    totals = await harvest_all_workspaces()

    assert totals["skipped_locked"] == 1
    assert totals["finance"] == 0


async def test_the_locked_out_result_has_the_same_shape_as_a_real_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers read these keys unconditionally; a missing one is an error."""
    monkeypatch.setattr(fleet, "get_redis", lambda: _HeldRedis())

    totals = await harvest_all_workspaces()

    assert set(totals) == set(fleet._EMPTY_TOTALS)


async def test_the_lock_is_freed_for_the_next_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed harvest must not leave the job blocked until the TTL."""
    redis = _HeldRedis()
    redis.store.clear()
    monkeypatch.setattr(fleet, "get_redis", lambda: redis)

    async def _no_workspaces(*args: object, **kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _no_workspaces)

    await harvest_all_workspaces()

    assert redis.store == {}


async def _no_tokens(workspace_id: uuid.UUID) -> WorkspaceTokenBundle | None:
    """A workspace with no WB credentials — these tests are about the lock only.

    The rate-limit peek reads the settlement bucket, which is named after the
    seller token; without one there is no bucket to consult and the service
    answers "ask now", which is the fail-open behaviour these tests want out of
    the way.
    """
    return None


class _StubDailyRepo:
    """No provisional tail — these tests are about the lock, not the tail.

    `None` is also the ordinary answer for a workspace whose settled history
    already reaches yesterday, so it is the right default rather than a
    convenience.
    """

    async def covered_through(self, *, workspace_id: uuid.UUID) -> date | None:
        return None


class _StubReportRepo:
    """Answers the one coverage question the control service asks."""

    def __init__(self, settled: date | None) -> None:
        self._header = (
            LatestReportHeader(
                report_id=969371534,
                date_from=settled - timedelta(days=6),
                date_to=settled,
                harvested_at=datetime(2026, 8, 11, 6, 14, tzinfo=UTC),
            )
            if settled is not None
            else None
        )

    async def latest_report(self, *, workspace_id: uuid.UUID) -> LatestReportHeader | None:
        return self._header


async def test_the_button_sees_a_harvest_that_is_already_running() -> None:
    """What the route turns into «уже выполняется» instead of a second run."""
    service = HarvestControlService(
        report_repo=_StubReportRepo(date(2026, 8, 9)),  # type: ignore[arg-type]
        daily_repo=_StubDailyRepo(),  # type: ignore[arg-type]
        redis=_HeldRedis(),  # type: ignore[arg-type]
        freshness_records=NullFreshnessRecordStore(),
        load_tokens=_no_tokens,
    )

    state = await service.get_state(workspace_id=WORKSPACE)

    assert state.running is True
    assert state.latest_settled == date(2026, 8, 9)


async def test_an_idle_lock_reads_as_not_running() -> None:
    """Otherwise the button would refuse to work for an hour after every run."""
    redis = _HeldRedis()
    redis.store.clear()
    service = HarvestControlService(
        report_repo=_StubReportRepo(None),  # type: ignore[arg-type]
        daily_repo=_StubDailyRepo(),  # type: ignore[arg-type]
        redis=redis,  # type: ignore[arg-type]
        freshness_records=NullFreshnessRecordStore(),
        load_tokens=_no_tokens,
    )

    state = await service.get_state(workspace_id=WORKSPACE)

    assert state.running is False
    assert state.latest_settled is None


async def test_an_unreachable_redis_does_not_block_the_button() -> None:
    """Fail open, the same way the lock itself does.

    Reporting "a harvest is running" because the cache is down would disable the
    one manual escape hatch precisely when the scheduled path is also degraded.
    """

    class _BrokenRedis:
        async def exists(self, key: str) -> int:
            raise RedisError("connection refused")

    service = HarvestControlService(
        report_repo=_StubReportRepo(None),  # type: ignore[arg-type]
        daily_repo=_StubDailyRepo(),  # type: ignore[arg-type]
        redis=_BrokenRedis(),  # type: ignore[arg-type]
        freshness_records=NullFreshnessRecordStore(),
        load_tokens=_no_tokens,
    )

    state = await service.get_state(workspace_id=WORKSPACE)

    assert state.running is False


async def test_the_button_reads_the_bucket_the_harvest_actually_spends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Обновить» must answer «rate_limited» from the endpoint in use today.

    It read the statistics gate on `reportDetailByPeriod` until 2026-09-23 — the
    endpoint the harvest left on 22.09 — so it inspected a bucket nothing writes
    to any more. It always answered «open», the route's `rate_limited` branch
    became unreachable, and a seller clicking into a standing block was told the
    harvest had started and then watched it not happen.
    """
    from src.integrations.wildberries.endpoints import SALES_REPORTS_DETAILED_PATH
    from src.modules.finreports.services import harvest_control

    asked: list[tuple[str, str]] = []

    class _Gate:
        def __init__(self, token: str) -> None:
            self.token = token

        async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
            asked.append((self.token, endpoint))
            return 391.0

    monkeypatch.setattr(
        harvest_control,
        "finance_reports_rate_gate",
        lambda _settings, *, token: _Gate(token),
    )

    async def _tokens(_workspace_id: uuid.UUID) -> WorkspaceTokenBundle:
        return WorkspaceTokenBundle(
            workspace_id=WORKSPACE,
            name="Демо",
            statistics="a-statistics-token",
            finance="a-finance-token",
        )

    service = HarvestControlService(
        report_repo=_StubReportRepo(None),  # type: ignore[arg-type]
        daily_repo=_StubDailyRepo(),  # type: ignore[arg-type]
        redis=_HeldRedis(),  # type: ignore[arg-type]
        freshness_records=NullFreshnessRecordStore(),
        load_tokens=_tokens,
    )

    retry_after = await service.settlement_retry_after(workspace_id=WORKSPACE)

    assert retry_after == 391.0
    assert asked == [("a-finance-token", SALES_REPORTS_DETAILED_PATH)]


async def test_the_button_does_not_refuse_over_the_next_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A minute of refill is queued through, not answered with «rate_limited».

    The fleet tick stopped reading the refill as a block on 2026-09-24; the
    button kept the old reading and refused for up to a minute after the
    backfill or the daily tail had taken a token.
    """
    from src.modules.finreports.services import harvest_control

    class _Gate:
        async def retry_after(self, _endpoint: str, *, reserve_seconds: float = 0.0) -> float:
            return 45.0

    monkeypatch.setattr(
        harvest_control, "finance_reports_rate_gate", lambda _settings, *, token: _Gate()
    )

    async def _tokens(_workspace_id: uuid.UUID) -> WorkspaceTokenBundle:
        return WorkspaceTokenBundle(workspace_id=WORKSPACE, name="NEVA", finance="a-finance-token")

    service = HarvestControlService(
        report_repo=_StubReportRepo(None),  # type: ignore[arg-type]
        daily_repo=_StubDailyRepo(),  # type: ignore[arg-type]
        redis=_HeldRedis(),  # type: ignore[arg-type]
        freshness_records=NullFreshnessRecordStore(),
        load_tokens=_tokens,
    )

    assert await service.settlement_retry_after(workspace_id=WORKSPACE) == 0.0
