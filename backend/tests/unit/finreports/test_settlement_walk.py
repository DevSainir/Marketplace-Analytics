"""What a week's failure costs, and where the walk waits.

`walk_settlement_windows` is the piece that turned a 28-day paged walk in one
transaction into a week per request with a transaction each. Three properties
carry that change, and none of them would fail loudly on its own:

* one request per week — a walk that batched them would be back inside WB's
  block within a second;
* a week that fails does not take the weeks that succeeded with it, and IS
  counted, so a partial P&L is visible rather than inferred;
* the wait for WB's next token happens before the session opens. The wait is
  minutes long and an open transaction is closed by PostgreSQL after 300 s,
  which is the exact failure this walk was rebuilt to avoid.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, ClassVar, Self

import pytest

from src.core.exceptions import IntegrationError
from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks.settlement import MissingReport, walk_settlement_reports
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

#: Two reports WB has formed and we do not hold, oldest first — the walk's
#: unit of work since the report replaced the date window on 2026-09-22.
_REPORTS = (
    MissingReport(report_id=801, date_to=date(2026, 8, 30)),
    MissingReport(report_id=802, date_to=date(2026, 9, 6)),
)
#: Just the first of them, for the cases about one report's paging.
_ONE_REPORT = _REPORTS[:1]

#: What "a full request" means to the walk, owned by the fake client below.
#:
#: Deliberately NOT the real client's 100 000. The walk must read the number off
#: the client rather than carry a copy of it — a fake whose limit differs from
#: production's is what makes that difference observable here, and building a
#: hundred thousand rows to prove it would cost every run of this file a second
#: and several hundred megabytes.
_STREAM_LIMIT = 4


class _Row:
    """The one field the walk reads off a settlement row: its cursor."""

    def __init__(self, rrd_id: int) -> None:
        self.rrd_id = rrd_id


def _row(index: int) -> _Row:
    """A settlement row whose `rrd_id` advances with the page."""
    return _Row(900_000_000_000 + index)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with the settlement scope and nothing else."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(), name="NEVA", statistics="stat-token", finance="a-finance-token"
    )


class _RecordingSession:
    """Records commits, and refuses to be open while the walk is waiting."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    async def __aenter__(self) -> Self:
        self._journal.append("session-open")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._journal.append("session-close")

    async def commit(self) -> None:
        self._journal.append("commit")


class _FakeIngestion:
    """Counts the rows each page carries, without a database."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    async def ingest_finance_report(self, pages: Any, *, workspace_id: uuid.UUID) -> int:
        total = 0
        async for page in pages:
            total += len(page)
        self._journal.append(f"ingest:{total}")
        return total

        return 0


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Order of operations across the whole walk, as one readable list."""
    entries: list[str] = []

    class _Gate:
        async def acquire(self, endpoint: str) -> None:
            entries.append(f"token:{endpoint}")

        async def observe(self, endpoint: str, remaining: int | None) -> None:
            return None

    class _Client:
        #: Reports whose walk raises, keyed by id.
        failing: ClassVar[set[int]] = set()

        def __init__(self, _settings: Any, **kwargs: Any) -> None:
            self._kwargs = kwargs

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        #: Reports served as two pages instead of one, keyed by id.
        paged: ClassVar[set[int]] = set()
        #: Reports whose SECOND page raises, keyed by id.
        failing_second: ClassVar[set[int]] = set()

        @property
        def stream_limit(self) -> int:
            return _STREAM_LIMIT

        async def stream_report_rows(self, *, report_id: int, cursor: int = 0) -> Any:
            entries.append(f"fetch:{report_id}@{cursor}")
            if report_id in (_Client.failing if cursor == 0 else _Client.failing_second):
                raise IntegrationError("WB withheld this page.")
            if report_id in _Client.paged and cursor == 0:
                # A full request, so the walk must come back for a second one.
                yield [_row(index) for index in range(_STREAM_LIMIT)]
                return
            yield [_row(1), _row(2)]

    _Client.failing = set()
    _Client.failing_second = set()
    _Client.paged = set()
    monkeypatch.setattr(settlement_module, "finance_reports_rate_gate", lambda *_a, **_k: _Gate())
    monkeypatch.setattr(settlement_module, "WBFinanceReportsClient", _Client)
    monkeypatch.setattr(settlement_module, "AsyncSessionLocal", lambda: _RecordingSession(entries))
    return entries


def _ingestion_factory(journal: list[str]) -> Any:
    """A `build_ingestion` the walk can call with its session."""
    return lambda _session: _FakeIngestion(journal)


async def test_each_page_is_one_request_and_one_commit(journal: list[str]) -> None:
    """Two one-page weeks: two requests, two transactions — not one paged walk.

    The unit is the page rather than the week because a week is not reliably
    one page: the first seller measured has weeks past the 10 000-row limit,
    and a second page is a second quarter-hour of WB's budget.
    """
    rows, failed, _through = await walk_settlement_reports(
        tokens=_tokens(),
        reports=_REPORTS,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (4, 0)
    assert journal == [
        "token:/api/finance/v1/sales-reports/detailed/{id}",
        "session-open",
        "fetch:801@0",
        "ingest:2",
        "commit",
        "session-close",
        "token:/api/finance/v1/sales-reports/detailed/{id}",
        "session-open",
        "fetch:802@0",
        "ingest:2",
        "commit",
        "session-close",
    ]


async def test_the_token_is_taken_before_the_session_is_opened(journal: list[str]) -> None:
    """The property the rebuild exists for.

    Waiting for WB's next quarter-hour with a transaction open is what had
    PostgreSQL close the harvest's connection on 2026-09-07. Every `token:`
    entry must therefore fall outside a `session-open`/`session-close` pair.
    """
    await walk_settlement_reports(
        tokens=_tokens(),
        reports=_REPORTS,
        build_ingestion=_ingestion_factory(journal),
    )

    depth = 0
    for entry in journal:
        if entry == "session-open":
            depth += 1
        elif entry == "session-close":
            depth -= 1
        elif entry.startswith("token:"):
            assert depth == 0, "a rate-token wait happened inside an open transaction"


async def test_a_week_wb_withholds_does_not_cost_the_weeks_that_worked(
    journal: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial span must be partial and SAID to be, not silently short.

    The count is what the caller turns into a failed source; without it a P&L
    missing a week looks exactly like a seller who sold nothing that week.
    """
    settlement_module.WBFinanceReportsClient.failing = {801}  # type: ignore[attr-defined]

    rows, failed, _through = await walk_settlement_reports(
        tokens=_tokens(),
        reports=_REPORTS,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (2, 1)
    assert "ingest:2" in journal


async def test_a_window_that_never_gets_a_token_is_counted_not_skipped(
    journal: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that gives up is a missing week, and must read as one.

    The gate raises when WB's next token is further away than the walk may
    wait. Treating that as "nothing to harvest" would leave the P&L short with
    every source reporting success.
    """

    class _RefusingGate:
        async def acquire(self, endpoint: str) -> None:
            raise IntegrationError("WB rate budget is further away than we may wait.")

        async def observe(self, endpoint: str, remaining: int | None) -> None:
            return None

    monkeypatch.setattr(
        settlement_module, "finance_reports_rate_gate", lambda *_a, **_k: _RefusingGate()
    )

    rows, failed, _through = await walk_settlement_reports(
        tokens=_tokens(),
        reports=_REPORTS,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (0, 2)
    assert "session-open" not in journal


async def test_a_workspace_without_the_settlement_scope_asks_for_nothing(
    journal: list[str],
) -> None:
    """No token, no request — and no rate budget spent proving it."""
    rows, failed, _through = await walk_settlement_reports(
        tokens=WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="Асель"),
        reports=_REPORTS,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (0, 0)
    assert journal == []


async def test_a_second_page_costs_a_second_token_and_a_second_transaction(
    journal: list[str],
) -> None:
    """A week is not reliably one page, and page two is another quarter-hour.

    Measured 2026-09-07: the first outside seller's very first week ran past
    the 10 000-row page limit, and the second page came back 429 with a
    fifteen-minute block. So the walk must take a fresh token for it — outside
    the transaction the first page committed in, not inside one held open
    across the wait.
    """
    settlement_module.WBFinanceReportsClient.paged = {801}  # type: ignore[attr-defined]

    rows, failed, _through = await walk_settlement_reports(
        tokens=_tokens(),
        reports=_ONE_REPORT,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (_STREAM_LIMIT + 2, 0)
    assert journal.count("token:/api/finance/v1/sales-reports/detailed/{id}") == 2
    assert journal.count("commit") == 2
    # The second request pages from the last row of the first, so no row is
    # fetched — or upserted — twice.
    assert journal[-4] == f"fetch:801@{900_000_000_000 + _STREAM_LIMIT - 1}"


async def test_a_page_committed_before_a_failure_is_kept(journal: list[str]) -> None:
    """Half a week is better than none, and honestly reported as half.

    All-or-nothing cannot span a fifteen-minute wait — PostgreSQL will not hold
    the transaction — so the page is the atomic unit. Every row is upserted by
    `rrd_id` and the next tick's span starts at the last settled day, so a week
    left half-loaded completes itself rather than staying wrong.
    """
    settlement_module.WBFinanceReportsClient.paged = {801}  # type: ignore[attr-defined]
    settlement_module.WBFinanceReportsClient.failing_second = {801}  # type: ignore[attr-defined]

    rows, failed, _through = await walk_settlement_reports(
        tokens=_tokens(),
        reports=_ONE_REPORT,
        build_ingestion=_ingestion_factory(journal),
    )

    # The first page is committed and kept; the week is reported incomplete
    # rather than reported as a week that small.
    assert (rows, failed) == (_STREAM_LIMIT, 1)
    assert journal.count("commit") == 1
