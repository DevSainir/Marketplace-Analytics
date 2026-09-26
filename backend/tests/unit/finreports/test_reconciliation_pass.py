"""The reconciliation PASS — the tick that actually re-walks the lost day.

Its two halves are chosen elsewhere and pinned in
``test_settlement_reconciliation``: the span that reaches behind the watermark,
and the rotation that decides whose turn it is. What is left, and what lives
here, is the tick itself — that it walks even when the freshness gate says
nothing is newer (which is true, and beside the point, exactly when a
back-dated report is what is being looked for), that it still yields to the
harvest lock, and that «Обновить» spends only the caller's own budget.

Split off on 2026-09-23 because the file had grown past the 500-line ceiling
and the seam was already there: everything above needed no fakes at all, and
everything here needs the whole harness.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from src.modules.finreports.constants import (
    HARVEST_LOCK_KEY,
    WB_REPORTS_EPOCH,
)
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
#: Where the watermark stood once the 01.09-06.09 report had landed.
SETTLED = date(2026, 9, 6)
#: The day that fell out of reach behind it.
LOST_DAY = date(2026, 8, 31)


# --- the pass -------------------------------------------------------------


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

    That verdict is the honest one all through this incident — WB really had
    published nothing past the watermark — and it is exactly what a
    back-dated report has to survive.
    """
    spans: list[tuple[date, date]] = []
    redis = _FakeRedis()

    bundle = WorkspaceTokenBundle(
        workspace_id=WORKSPACE, name="Демо", statistics="stat-token", finance="fin-token"
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
        spans.append((reports[0].date_to, reports[-1].date_to) if reports else (TODAY, TODAY))
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

    async def _no_archive(**_kwargs: object) -> None:
        # A real list request through a real rate gate; its own test is below.
        return None

    monkeypatch.setattr(fleet, "refresh_archive_totals", _no_archive)

    # The gap survey is a database read and this is the unit tier. Stubbed to
    # "history is sound" so these tests exercise the walk rather than the
    # detector — which has its own tests against real SQL, because
    # `generate_series` over a date range is not Python behaviour.
    async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {}

    monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
    return spans


async def test_an_ordinary_tick_still_skips_when_nothing_is_newer(
    walked: list[tuple[date, date]],
) -> None:
    """The gate keeps its job — this pass must not turn every hour into a walk."""
    totals = await harvest_all_workspaces()

    assert walked == []
    assert totals["workspaces_skipped"] == 1


async def test_the_reconciliation_pass_walks_despite_a_gate_that_says_no(
    walked: list[tuple[date, date]],
) -> None:
    """«Ничего новее нет» is true and irrelevant when the missing report is older.

    The gate probes the day AFTER the watermark, so it cannot see a back-dated
    report even in principle. Letting its verdict stop the pass would leave the
    lookback span unreachable and the fix inert.
    """
    await harvest_all_workspaces(reconcile=True)

    assert len(walked) == 1


async def test_the_reconciliation_pass_asks_about_the_day_that_was_lost(
    walked: list[tuple[date, date]],
) -> None:
    """The two halves together: it runs, and it runs over the right span."""
    await harvest_all_workspaces(reconcile=True)

    date_from, date_to = walked[0]
    assert date_from <= LOST_DAY <= date_to


async def test_the_reconciliation_pass_still_respects_the_harvest_lock(
    walked: list[tuple[date, date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is the same walk against the same WB budget, so it queues like one.

    Two of these racing would spend a seller's quarter-hourly settlement budget
    twice over — the failure the lock exists to prevent, and one the extra span
    would make more expensive, not less.
    """
    held = _FakeRedis()
    held.store[HARVEST_LOCK_KEY] = "another-runs-token"
    monkeypatch.setattr(fleet, "get_redis", lambda: held)

    totals = await harvest_all_workspaces(reconcile=True)

    assert walked == []
    assert totals["skipped_locked"] == 1


async def test_the_button_walks_the_lookback_for_its_own_workspace(
    walked: list[tuple[date, date]],
) -> None:
    """«Обновить» asks the thorough question, scoped to the caller.

    It used to ask the forward one, on the reasoning that widening a click into a
    fortnight of re-reads spends a seller's settlement budget on data already on
    file — and that the daily pass covers it anyway. The cost was right; the
    «anyway» was not. The daily pass takes one workspace a night, so a seller
    short a week waits up to five days, and this button exists for exactly the
    case where the schedule has already failed to fetch something WB has.
    """
    await harvest_all_workspaces(workspace_id=WORKSPACE, reconcile=True)

    date_from, date_to = walked[0]
    assert date_from <= LOST_DAY <= date_to


async def test_the_button_still_spends_only_the_callers_budget(
    walked: list[tuple[date, date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The thorough span must not come with a fleet-wide walk attached.

    A click is one tenant's, and the cost of one click may not grow with the
    number of sellers on the platform.
    """
    loaded: list[uuid.UUID | None] = []

    async def _fleet(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        loaded.append(None)
        return []

    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _fleet)

    await harvest_all_workspaces(workspace_id=WORKSPACE, reconcile=True)

    assert loaded == []
    assert len(walked) == 1


async def test_the_nightly_pass_reconciles_every_seller(
    walked: list[tuple[date, date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every кабинет is re-read each night, not one in rotation.

    The ration was sized for an endpoint serving four requests an hour, where a
    fortnight's re-walk was three quarter-hour windows per seller. On
    finance-api it is a few requests a minute apart, so a seller waited for its
    turn — up to the size of the fleet in nights — for no saving.
    """
    fleet_of_three = [
        WorkspaceTokenBundle(
            workspace_id=uuid.uuid5(uuid.NAMESPACE_DNS, name), name=name, finance="fin-token"
        )
        for name in ("Демо", "NEVA", "Олег")
    ]

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return fleet_of_three

    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)

    await harvest_all_workspaces(reconcile=True)

    assert len(walked) == 3


async def test_the_nightly_pass_re_walks_a_short_report_however_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An archive report that does not add up to WB's total is asked for again.

    The forward tick looks back 45 days and the history backfill runs once, so
    on an established кабинет nothing else would ever fetch it.
    """
    old = SETTLED - timedelta(days=400)

    class _ShortArchive(_FakeReportRepo):
        async def incomplete_report_ids(self, *, workspace_id: uuid.UUID) -> set[int]:
            return {600}

        async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
            return [(600, old - timedelta(days=6), old), (702, SETTLED, SETTLED)]

    monkeypatch.setattr(ledger, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(ledger, "FinancialReportRepository", _ShortArchive)

    reports = await ledger.reports_to_re_walk(report_repo_for=WORKSPACE, today=TODAY)

    assert [report.report_id for report in reports] == [600, 702]


async def test_the_nightly_pass_asks_for_the_whole_history_s_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One list request from the epoch, and what it names goes to the totals.

    A кабинет older than the totals held them on eight of 143 reports, and the
    completeness check is blind wherever a total is missing.
    """
    asked: list[tuple[date, date]] = []
    recorded: list[int] = []

    class _Client:
        def __init__(self, _settings: object, *, token: str) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def list_reports(self, *, date_from: date, date_to: date) -> list[str]:
            asked.append((date_from, date_to))
            return ["report-1", "report-2"]

    async def _record(*, workspace_id: uuid.UUID, listed: list[str]) -> None:
        recorded.append(len(listed))

    monkeypatch.setattr(ledger, "WBFinanceReportsClient", _Client)
    monkeypatch.setattr(ledger, "record_wb_totals", _record)
    tokens = WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", finance="fin-token")

    await ledger.refresh_archive_totals(tokens=tokens, today=TODAY)

    assert asked == [(WB_REPORTS_EPOCH, TODAY)]
    assert recorded == [2]
