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
from types import SimpleNamespace
from typing import Any, ClassVar, Self

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks.settlement import walk_settlement_windows
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

_FROM, _TO = date(2026, 8, 24), date(2026, 9, 6)  # two weeks

#: The client's own page size, which is what "a full page" means to the walk.
_PAGE_LIMIT = WBFinanceClient(
    SimpleNamespace(  # type: ignore[arg-type]
        wb_statistics_base_url="https://wb.test",
        wb_http_timeout_seconds=1.0,
        wb_max_retries=0,
        wb_retry_backoff_seconds=0.0,
        wb_retry_max_backoff_seconds=0.0,
        wb_rate_pacing_enabled=False,
    ),
    token="probe",
).page_limit


class _Row:
    """The one field the walk reads off a settlement row: its cursor."""

    def __init__(self, rrd_id: int) -> None:
        self.rrd_id = rrd_id


def _row(index: int) -> _Row:
    """A settlement row whose `rrd_id` advances with the page."""
    return _Row(900_000_000_000 + index)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with the settlement scope and nothing else."""
    return WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="NEVA", statistics="stat-token")


class _RecordingSession:
    """Records commits, and refuses to be open while the walk is waiting."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    async def __aenter__(self) -> Self:
        self._journal.append("session-open")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._journal.append("session-close")

    def begin_nested(self) -> _Savepoint:
        return _Savepoint(self._journal)

    async def commit(self) -> None:
        self._journal.append("commit")


class _Savepoint:
    """The per-week savepoint, which is not the session."""

    def __init__(self, journal: list[str]) -> None:
        self._journal = journal

    async def __aenter__(self) -> Self:
        self._journal.append("savepoint")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


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
        #: Windows whose walk raises, keyed by their start date.
        failing: ClassVar[set[date]] = set()

        def __init__(self, _settings: Any, **kwargs: Any) -> None:
            self._kwargs = kwargs

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        #: Windows served as two pages instead of one, keyed by start date.
        paged: ClassVar[set[date]] = set()
        #: Windows whose SECOND page raises, keyed by start date.
        failing_second: ClassVar[set[date]] = set()

        @property
        def page_limit(self) -> int:
            return _PAGE_LIMIT

        async def fetch_report_page(
            self, *, date_from: date, date_to: date, cursor: int = 0
        ) -> list[Any]:
            entries.append(f"fetch:{date_from}..{date_to}@{cursor}")
            if date_from in (_Client.failing if cursor == 0 else _Client.failing_second):
                raise IntegrationError("WB withheld this page.")
            if date_from in _Client.paged and cursor == 0:
                # A full page, so the walk must come back for a second one.
                return [_row(index) for index in range(_PAGE_LIMIT)]
            return [_row(1), _row(2)]

    _Client.failing = set()
    _Client.failing_second = set()
    _Client.paged = set()
    monkeypatch.setattr(settlement_module, "settlement_walk_rate_gate", lambda *_a, **_k: _Gate())
    monkeypatch.setattr(settlement_module, "WBFinanceClient", _Client)
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
    rows, failed, _through = await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=_TO,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (4, 0)
    assert journal == [
        "token:/api/v5/supplier/reportDetailByPeriod",
        "session-open",
        "savepoint",
        "fetch:2026-08-24..2026-08-30@0",
        "ingest:2",
        "commit",
        "session-close",
        "token:/api/v5/supplier/reportDetailByPeriod",
        "session-open",
        "savepoint",
        "fetch:2026-08-31..2026-09-06@0",
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
    await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=_TO,
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
    settlement_module.WBFinanceClient.failing = {date(2026, 8, 24)}  # type: ignore[attr-defined]

    rows, failed, _through = await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=_TO,
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
        settlement_module, "settlement_walk_rate_gate", lambda *_a, **_k: _RefusingGate()
    )

    rows, failed, _through = await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=_TO,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (0, 2)
    assert "session-open" not in journal


async def test_a_workspace_without_the_settlement_scope_asks_for_nothing(
    journal: list[str],
) -> None:
    """No token, no request — and no rate budget spent proving it."""
    rows, failed, _through = await walk_settlement_windows(
        tokens=WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="Асель"),
        date_from=_FROM,
        date_to=_TO,
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
    settlement_module.WBFinanceClient.paged = {date(2026, 8, 24)}  # type: ignore[attr-defined]

    rows, failed, _through = await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=date(2026, 8, 30),  # one week, served as two pages
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (_PAGE_LIMIT + 2, 0)
    assert journal.count("token:/api/v5/supplier/reportDetailByPeriod") == 2
    assert journal.count("commit") == 2
    # The second request pages from the last row of the first, so no row is
    # fetched — or upserted — twice.
    assert journal[-4] == f"fetch:2026-08-24..2026-08-30@{900_000_000_000 + _PAGE_LIMIT - 1}"


async def test_a_page_committed_before_a_failure_is_kept(journal: list[str]) -> None:
    """Half a week is better than none, and honestly reported as half.

    All-or-nothing cannot span a fifteen-minute wait — PostgreSQL will not hold
    the transaction — so the page is the atomic unit. Every row is upserted by
    `rrd_id` and the next tick's span starts at the last settled day, so a week
    left half-loaded completes itself rather than staying wrong.
    """
    settlement_module.WBFinanceClient.paged = {date(2026, 8, 24)}  # type: ignore[attr-defined]
    settlement_module.WBFinanceClient.failing_second = {  # type: ignore[attr-defined]
        date(2026, 8, 24)
    }

    rows, failed, _through = await walk_settlement_windows(
        tokens=_tokens(),
        date_from=_FROM,
        date_to=date(2026, 8, 30),
        build_ingestion=_ingestion_factory(journal),
    )

    # The first page is committed and kept; the week is reported incomplete
    # rather than reported as a week that small.
    assert (rows, failed) == (_PAGE_LIMIT, 1)
    assert journal.count("commit") == 1
