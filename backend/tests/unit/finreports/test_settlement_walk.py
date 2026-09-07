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
from collections.abc import AsyncGenerator
from datetime import date
from typing import Any, ClassVar, Self

import pytest

from src.core.exceptions import IntegrationError
from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks.settlement import walk_settlement_windows
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

_FROM, _TO = date(2026, 8, 24), date(2026, 9, 6)  # two weeks


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

        async def iter_report_pages(
            self, *, date_from: date, date_to: date
        ) -> AsyncGenerator[list[str], None]:
            entries.append(f"fetch:{date_from}..{date_to}")
            if date_from in _Client.failing:
                raise IntegrationError("WB withheld this week.")
            yield ["row", "row"]

    _Client.failing = set()
    monkeypatch.setattr(settlement_module, "settlement_walk_rate_gate", lambda *_a, **_k: _Gate())
    monkeypatch.setattr(settlement_module, "WBFinanceClient", _Client)
    monkeypatch.setattr(settlement_module, "AsyncSessionLocal", lambda: _RecordingSession(entries))
    return entries


def _ingestion_factory(journal: list[str]) -> Any:
    """A `build_ingestion` the walk can call with its session."""
    return lambda _session: _FakeIngestion(journal)


async def test_each_week_is_one_request_and_one_commit(journal: list[str]) -> None:
    """Two weeks, two requests, two transactions — not one walk of two pages."""
    rows, failed = await walk_settlement_windows(
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
        "fetch:2026-08-24..2026-08-30",
        "ingest:2",
        "commit",
        "session-close",
        "token:/api/v5/supplier/reportDetailByPeriod",
        "session-open",
        "savepoint",
        "fetch:2026-08-31..2026-09-06",
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

    rows, failed = await walk_settlement_windows(
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

    rows, failed = await walk_settlement_windows(
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
    rows, failed = await walk_settlement_windows(
        tokens=WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="Асель"),
        date_from=_FROM,
        date_to=_TO,
        build_ingestion=_ingestion_factory(journal),
    )

    assert (rows, failed) == (0, 0)
    assert journal == []
