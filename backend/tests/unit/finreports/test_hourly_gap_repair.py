"""A hole we can already see is walked within the hour, not within the week.

The detector (:mod:`src.modules.finreports.tasks.gaps`) and the nightly rotation
were built in the same change and left one gap between them: the rotation takes
ONE workspace a night. A seller short a settlement week could therefore be
reported every night for four nights before anything went and fetched it, while
the report was fetchable the whole time. On 2026-09-14 three workspaces were
short the entire 07.09-13.09 week and the queue would have reached the last of
them on the 18th.

So the hourly tick repairs too. The two bounds below are what keep that
affordable, and they are the whole subject of these tests: one workspace a tick,
and a cooldown per workspace — because a day WB will never serve stays visible
forever, and an unrationed repair would spend a fortnight-wide walk on it every
hour, holding the fleet-wide lock against everyone else's cheap forward probe.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from redis.exceptions import RedisError

from src.modules.finreports.constants import GAP_REPAIR_COOLDOWN_PREFIX
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.finreports.tasks import freshness, repair
from src.modules.finreports.tasks.harvest import fleet, harvest_all_workspaces, ledger
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.contract import WorkspaceTokenBundle
from tests.support.fakes import no_daily_tail

pytestmark = pytest.mark.unit


async def _never_blocked(_tokens: object) -> float:
    """No penalty block stands.

    Stubbed rather than left to the real gate because the real gate reaches
    Redis, and a unit test that quietly talks to a live Redis drains the
    bucket a developer's next run depends on.
    """
    return 0.0


WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ab99")
TODAY = date(2026, 9, 8)
#: Where the watermark stood once the weekly report had landed.
SETTLED = date(2026, 9, 6)
#: The day that fell out of reach behind it.
LOST_DAY = date(2026, 8, 31)


class _FakeRedis:
    """The lock commands plus the two the freshness record uses."""

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


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    """Reports the watermark as it stood once the weekly report had landed."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SETTLED


class _FakeReportRepo:
    """Coverage after the walk — unchanged, which is the quiet-week case."""

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        return SETTLED

    async def report_ids_since(self, *, workspace_id: uuid.UUID, since: date) -> set[int]:
        """No report ids held, so WB's whole list reads as missing."""
        return set()

    async def incomplete_report_ids(self, *, workspace_id: uuid.UUID) -> set[int]:
        """Nothing here is short of its own rows.

        Production subtracts these from «held», because a header written beside
        the first batch outlives a fetch that died half-way. This fixture's
        headers are whole, so the honest answer is an empty set.
        """
        return set()

    async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
        """What a thorough pass re-walks: the reports on file, newest first.

        «Which ids am I missing» cannot see an amendment to a report already
        held, and amendments are what the reconciliation pass exists for.
        """
        return [
            (701, SETTLED - timedelta(days=10), SETTLED - timedelta(days=10)),
            (702, SETTLED, SETTLED),
        ]


@pytest.fixture
def walked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[date, date]]:
    """Wire a fleet of one whose gate says there is nothing newer.

    That verdict is the honest one whenever a hole is behind our coverage: WB
    really has published nothing past it, and the probe cannot see a day it does
    not ask about. A repair that waited for the gate's permission would never
    run, which is why these tests hold the gate closed throughout.
    """
    spans: list[tuple[date, date]] = []
    redis = _FakeRedis()

    bundle = WorkspaceTokenBundle(
        workspace_id=WORKSPACE, name="Demo", statistics="stat-token", finance="a-finance-token"
    )

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return [bundle]

    async def _bundle(*_args: object, **_kwargs: object) -> WorkspaceTokenBundle:
        return bundle

    async def _check(**_kwargs: object) -> tuple[FreshnessVerdict, tuple[()], tuple[()]]:
        return (
            FreshnessVerdict(
                outcome=FreshnessOutcome.WB_EMPTY,
                checked_at=datetime(2026, 9, 8, 3, 0, tzinfo=UTC),
                probe_from=date(2026, 9, 7),
                probe_to=date(2026, 9, 7),
            ),
            (),
            (),
        )

    async def _walk(
        *, tokens: WorkspaceTokenBundle, reports: tuple[MissingReport, ...], **_kwargs: object
    ) -> dict[str, int]:
        spans.append((reports[0].date_to, reports[-1].date_to))
        return {"finance_windows_failed": 0}

    monkeypatch.setattr(fleet, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(repair, "get_redis", lambda: redis)
    monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(freshness, "AsyncSessionLocal", _FakeSession)
    # The report ledger moved to its own module on 2026-09-23 and these fakes
    # have to follow it, or the tick opens a REAL session — which on a laptop
    # with Docker up passes, and in CI fails as "attached to a different loop".
    monkeypatch.setattr(ledger, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(ledger, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    # The loop reads BOTH — the frontier is the earlier of them. See
    # `tests/unit/finreports/test_settlement_frontier.py` for why.
    monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(freshness, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(fleet, "load_workspace_token_bundle", _bundle)
    monkeypatch.setattr(fleet, "settlement_blocked_for", _never_blocked)
    monkeypatch.setattr(fleet, "check_freshness", _check)
    monkeypatch.setattr(fleet, "harvest_workspace", _walk)
    monkeypatch.setattr(fleet, "tail_one_workspace", no_daily_tail)
    monkeypatch.setattr(fleet, "moscow_today", lambda: TODAY)

    # The gap survey is a database read and this is the unit tier. Stubbed to
    # "history is sound" so these tests exercise the walk rather than the
    # detector — which has its own tests against real SQL, because
    # `generate_series` over a date range is not Python behaviour.
    async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {}

    monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
    return spans


@pytest.fixture
def holed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the survey report a hole the nightly rotation has not reached yet."""

    async def _gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {WORKSPACE: [LOST_DAY]}

    monkeypatch.setattr(fleet, "survey_settlement_gaps", _gaps)


async def test_an_hourly_tick_repairs_a_hole_it_can_see(
    walked: list[tuple[date, date]], holed: None
) -> None:
    """The wait this removes: a visible hole used to sit until its rotation turn.

    The detector found it every night and the repair took one workspace a night,
    so a seller short a settlement week could be told about it four nights before
    anything went and fetched it — while the report was fetchable the whole time.
    """
    await harvest_all_workspaces()

    date_from, date_to = walked[0]
    assert date_from <= LOST_DAY <= date_to


async def test_a_repaired_workspace_is_not_walked_again_within_the_cooldown(
    walked: list[tuple[date, date]], holed: None
) -> None:
    """A hole WB will never serve stays visible, and those exist.

    Unrationed, every tick would spend a fortnight-wide walk on the same
    unfixable day for good — holding the fleet-wide lock against every other
    workspace's cheap forward probe.
    """
    await harvest_all_workspaces()
    await harvest_all_workspaces()

    assert len(walked) == 1


async def test_a_repair_that_cannot_be_rationed_is_not_started(
    walked: list[tuple[date, date]], holed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail CLOSED here, unlike the freshness gate, because the walk is the
    unbounded thing rather than the silence.

    The nightly pass still reaches it; an hourly walk nobody can ration does not
    stop at one.
    """

    class _NoClaimRedis(_FakeRedis):
        async def set(self, key: str, value: str, **kwargs: object) -> bool | None:
            if key.startswith(GAP_REPAIR_COOLDOWN_PREFIX):
                raise RedisError("connection refused")
            return await super().set(key, value, **kwargs)  # type: ignore[arg-type]

    redis = _NoClaimRedis()
    monkeypatch.setattr(repair, "get_redis", lambda: redis)

    totals = await harvest_all_workspaces()

    assert walked == []
    assert totals["workspaces_skipped"] == 1


async def test_a_sound_history_still_leaves_the_hourly_tick_cheap(
    walked: list[tuple[date, date]],
) -> None:
    """No hole, no walk — the repair must not become an hourly fortnight.

    The `walked` fixture's survey reports a sound history, which is the ordinary
    case and the one the schedule's affordability rests on.
    """
    totals = await harvest_all_workspaces()

    assert walked == []
    assert totals["workspaces_skipped"] == 1
