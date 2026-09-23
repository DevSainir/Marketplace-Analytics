"""The settlement walk must stream, not accumulate.

`WBFinanceReportsClient` used to return a whole settlement window as one list, so the
harvest's peak memory was a function of how much the seller had sold. It grew on
its own — no code change — until on 2026-08-11 it crossed the worker's cgroup
limit and the harvest was OOM-killed mid-walk (`signal 9`), leaving the week
unharvested. A settlement row costs ~9.7 KB while it is being validated, so the
old 100 000-row page alone was ~1 GB.

Memory is not something a normal assertion can see. The client's half of that
property — that nothing larger than one batch is ever held — is counted
directly in `tests/unit/integrations/test_wb_streaming_reader.py`; the tests
here pin what the streaming rewrite had to preserve on the way into the
database, each of which would otherwise fail quietly rather than loudly:

* a report whose rows straddle a page boundary keeps the period WB stated, not
  the last page's slice of it;
* a walk that dies part-way through writes nothing (a half-ingested settlement
  window is exactly the plausible-but-wrong state `docs/finreports/PNL.md` warns
  about);
* pages reaching the upsert carry no duplicate key, which PostgreSQL rejects for
  the whole batch rather than for the offending row.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.rate_limit import NullRateGate
from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.modules.finreports.services.ingestion.service import IngestionService

pytestmark = pytest.mark.unit

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: `rrd_id`s live in a range no other test uses, so a row built here is
#: recognisable wherever it surfaces.
_RRD_BASE = 900_000_000_000


def _row(index: int, *, report_id: int = 969371534, **extra: Any) -> dict[str, Any]:
    """One raw WB settlement row, `rrd_id` drawn from this module's range."""
    return {
        "rrd_id": _RRD_BASE + index,
        "realizationreport_id": report_id,
        "rr_dt": "2026-07-15",
        "currency_name": "KGS",
        **extra,
    }


class _RecordingRepo:
    """Captures what a repository was asked to upsert, in order."""

    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []

    async def bulk_upsert(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        """Record the batch and report it as written."""
        self.batches.append([dict(row) for row in rows])
        return len(rows)


def _ingestion(transactions: Any, reports: Any) -> IngestionService:
    """An ingestion service wired to fakes for the two repos this path uses."""
    unused: Any = None
    return IngestionService(
        transaction_repo=transactions,
        report_repo=reports,
        baseline_repo=unused,
        billed_repo=unused,
        penalty_repo=unused,
        measurement_repo=unused,
    )


async def _pages(*pages: list[dict[str, Any]]) -> AsyncGenerator[list[WBReportDetailRow], None]:
    """Yield raw rows as validated pages, the way the client does."""
    for page in pages:
        yield [WBReportDetailRow.model_validate(row) for row in page]


async def test_each_page_is_written_before_the_next_is_asked_for() -> None:
    """Ingestion happens per page — otherwise streaming buys nothing."""
    transactions, reports = _RecordingRepo(), _RecordingRepo()
    written = await _ingestion(transactions, reports).ingest_finance_report(
        _pages([_row(1), _row(2)], [_row(3)]), workspace_id=_WORKSPACE
    )

    assert written == 3
    assert [len(batch) for batch in transactions.batches] == [2, 1]


async def test_a_report_split_across_pages_keeps_the_period_wb_stated() -> None:
    """The last page must not narrow a period the first page established.

    WB leaves `date_from`/`date_to` blank on some rows, and the header then
    falls back to `rr_dt`. Build each page's headers in isolation and the second
    page overwrites the week with its own settlement days — a six-day «week»
    that shifts every week-scoped figure on the statement and in the claim.
    """
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    await _ingestion(transactions, reports).ingest_finance_report(
        _pages(
            [_row(1, rr_dt="2026-07-13")],
            [_row(2, rr_dt="2026-07-19")],
        ),
        workspace_id=_WORKSPACE,
    )

    final = reports.batches[-1]
    assert len(final) == 1
    assert final[0]["date_from"] == date(2026, 7, 13)
    assert final[0]["date_to"] == date(2026, 7, 19)


async def test_a_duplicate_key_inside_one_page_never_reaches_the_upsert() -> None:
    """`ON CONFLICT DO UPDATE` rejects the whole batch over one repeated key."""
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    await _ingestion(transactions, reports).ingest_finance_report(
        _pages([_row(1), _row(1), _row(2)]), workspace_id=_WORKSPACE
    )

    keys = [row["rrd_id"] for row in transactions.batches[0]]
    assert sorted(keys) == [_RRD_BASE + 1, _RRD_BASE + 2]


async def test_a_walk_that_fails_part_way_surfaces_the_failure() -> None:
    """A mid-walk failure must propagate, having written the pages before it.

    Both halves matter. The pages *are* written — streaming is what makes that
    unavoidable — so something has to undo them, and that something is the
    caller's SAVEPOINT (`harvest_workspace`, proved against a real transaction
    in `tests/integration/finreports/test_harvest_is_atomic.py`). Swallowing
    the error here would commit half a settlement window instead.
    """
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    async def failing() -> AsyncGenerator[list[WBReportDetailRow], None]:
        yield [WBReportDetailRow.model_validate(_row(1))]
        raise IntegrationError("WB gave up mid-walk.")

    with pytest.raises(IntegrationError, match="mid-walk"):
        await _ingestion(transactions, reports).ingest_finance_report(
            failing(), workspace_id=_WORKSPACE
        )

    assert len(transactions.batches) == 1


async def test_the_walks_inner_gate_forwards_a_penalty_but_not_the_budget_header() -> None:
    """A block reaches the shared bucket; a spent page's header does not.

    The walk hands its client a gate that says "this page already paid" — it
    must stay silent about `x-ratelimit-remaining`, or a page the walk has
    bought would clamp the shared bucket to zero underneath every other caller.
    A penalty block is the opposite case and has to travel: it describes a
    window nobody may enter, and the walk is precisely the caller that collects
    those 429s. Swallowing it here is how the hourly finance tick spent
    2026-09-08 re-entering a block it had already been told about.
    """
    from src.modules.finreports.tasks.settlement.page import _SpentToken

    shared = _RecordingGate()
    gate = _SpentToken(shared)

    await gate.observe("/api/v5/supplier/reportDetailByPeriod", 0)
    await gate.penalise("/api/v5/supplier/reportDetailByPeriod", 694.0)

    assert shared.observed == []
    assert shared.penalised == [("/api/v5/supplier/reportDetailByPeriod", 694.0)]


class _RecordingGate:
    """A stand-in for the walk's shared bucket that only remembers what it was told."""

    def __init__(self) -> None:
        """Start with empty logs."""
        self.observed: list[tuple[str, int | None]] = []
        self.penalised: list[tuple[str, float]] = []

    async def acquire(self, endpoint: str) -> None:
        """Never wait; this gate exists to be inspected, not to pace."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Record a budget-header observation that reached the shared bucket."""
        self.observed.append((endpoint, remaining))

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Record a penalty block that reached the shared bucket."""
        self.penalised.append((endpoint, seconds))


class _CountingSession:
    """A session that records commits and nothing else."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> _CountingSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def test_a_streamed_page_commits_every_batch_as_it_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Streaming bounded what we PARSE; it left what we had not committed growing.

    One transaction over a 100 000-row page held fifty batches of statement
    state at once and the kernel took the worker on 2026-09-15 — SIGKILL,
    anon-rss 417 MB against a 768 MiB cap. The parse buffer was bounded the
    whole time; the ceiling had simply moved to the transaction.

    So the commit belongs with the batch. Per-page atomicity was never
    load-bearing here: the cursor only advances on success and the ingest is an
    upsert, so a half-written page is re-fetched to the same result.
    """
    from src.modules.finreports.tasks.settlement import page as settlement

    session = _CountingSession()
    batches = [[_row(i)] for i in range(5)]

    class _Client:
        stream_limit = 100_000

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def stream_report_rows(self, **_kw: Any) -> Any:
            for raw in batches:
                yield [WBReportDetailRow.model_validate(row) for row in raw]

    class _Ingestion:
        async def ingest_settlement_rows(self, pages: Any, **_kw: Any) -> int:
            written = 0
            async for page in pages:
                written += len(page)
            return written

    monkeypatch.setattr(settlement, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(settlement, "WBFinanceReportsClient", lambda *a, **k: _Client())

    outcome = await settlement._ingest_one_streamed_page(
        tokens=SimpleNamespace(
            statistics="t", finance="a-finance-token", workspace_id=uuid.uuid4(), name="NEVA"
        ),
        report_id=989286628,
        cursor=0,
        build_ingestion=lambda _s: _Ingestion(),
        gate=NullRateGate(),
    )

    assert (outcome.rows, outcome.next_cursor, outcome.ok) == (5, None, True)
    assert session.commits == len(batches), (
        f"committed {session.commits} times for {len(batches)} batches — the page "
        "is still one transaction"
    )


async def test_a_full_request_that_does_not_advance_ends_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled `rrdid` must end the window, not be asked for forever.

    The walk's exit test is "fewer rows than we asked for". WB could serve a
    full request whose last `rrd_id` is the one we paged FROM any day, and
    without this guard the window would be re-fetched at one request per
    fifteen minutes until somebody noticed — spending the token budget every
    other workspace's harvest needs. The guard used to be the client's, in the
    generator that owned the loop; it moved here with the cursor.
    """
    from src.modules.finreports.tasks.settlement import page as settlement

    session = _CountingSession()
    cursor = _RRD_BASE + 10

    class _StalledClient:
        #: Matches the row count below, so the request reads as a FULL one and
        #: the short-request exit does not fire before the guard is reached.
        stream_limit = 2

        async def __aenter__(self) -> _StalledClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def stream_report_rows(self, **_kw: Any) -> Any:
            """Serve a full request that ends on the row we paged from."""
            yield [
                WBReportDetailRow.model_validate(_row(9)),
                WBReportDetailRow.model_validate(_row(10)),
            ]

    class _Ingestion:
        async def ingest_settlement_rows(self, pages: Any, **_kw: Any) -> int:
            written = 0
            async for page in pages:
                written += len(page)
            return written

    monkeypatch.setattr(settlement, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(settlement, "WBFinanceReportsClient", lambda *a, **k: _StalledClient())

    outcome = await settlement._ingest_one_streamed_page(
        tokens=SimpleNamespace(
            statistics="t", finance="a-finance-token", workspace_id=uuid.uuid4(), name="NEVA"
        ),
        report_id=989286628,
        cursor=cursor,
        build_ingestion=lambda _s: _Ingestion(),
        gate=NullRateGate(),
    )

    # The rows it did serve are kept and committed; the window simply ends.
    assert (outcome.rows, outcome.next_cursor, outcome.ok) == (2, None, True)
