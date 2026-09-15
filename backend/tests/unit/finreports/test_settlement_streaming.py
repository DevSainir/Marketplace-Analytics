"""The settlement walk must stream, not accumulate.

`WBFinanceClient` used to return a whole settlement window as one list, so the
harvest's peak memory was a function of how much the seller had sold. It grew on
its own — no code change — until on 2026-08-11 it crossed the worker's cgroup
limit and the harvest was OOM-killed mid-walk (`signal 9`), leaving the week
unharvested. A settlement row costs ~9.7 KB while it is being validated, so the
old 100 000-row page alone was ~1 GB.

Memory is not something a normal assertion can see, which is why the first test
here counts live model instances directly: it fails if a future refactor
reintroduces an accumulator, and no other test would.

The rest pin the properties the streaming rewrite had to preserve, each of which
would otherwise fail quietly rather than loudly:

* a report whose rows straddle a page boundary keeps the period WB stated, not
  the last page's slice of it;
* a walk that dies part-way through writes nothing (a half-ingested settlement
  window is exactly the plausible-but-wrong state `docs/finreports/PNL.md` warns
  about);
* pages reaching the upsert carry no duplicate key, which PostgreSQL rejects for
  the whole batch rather than for the offending row.
"""

from __future__ import annotations

import gc
import uuid
from collections.abc import AsyncGenerator, Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.integrations.wildberries.rate_limit import NullRateGate
from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.modules.finreports.services.ingestion.service import IngestionService

pytestmark = pytest.mark.unit

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: Rows the fake WB serves per page in these tests. Small enough to keep them
#: fast; the property under test does not depend on the size.
_PAGE = 4

#: `rrd_id`s live in a range no other test uses, so the live-object count below
#: cannot be polluted by rows another module left reachable.
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


def _paged_transport(pages: Sequence[list[dict[str, Any]]]) -> httpx.MockTransport:
    """Serve `pages` in order, one per request, then an empty page.

    Answers whatever the client asks for rather than honouring the `rrdid`
    cursor: the cursor is the client's business and is asserted separately.
    """
    remaining = list(pages)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remaining.pop(0) if remaining else [])

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport, *, page_limit: int = _PAGE) -> WBFinanceClient:
    """A finance client whose transport is fake and whose page size is tiny.

    Pacing off: the settlement walk takes one token per page from a bucket
    that refills every 61 s, so a paced multi-page test would spend minutes
    asleep proving nothing about the walk. The gate has its own tests in
    ``tests/unit/integrations/test_wb_rate_pacing.py``.
    """
    from src.core.config import settings

    client = WBFinanceClient(
        settings.model_copy(update={"wb_rate_pacing_enabled": False}), token="stat-token"
    )
    client._PAGE_LIMIT = page_limit  # type: ignore[misc]
    client._client = httpx.AsyncClient(base_url="https://wb.test", transport=transport)
    return client


def _live_rows() -> int:
    """How many settlement models built by this module are still reachable."""
    gc.collect()
    return sum(
        1 for obj in gc.get_objects() if type(obj) is WBReportDetailRow and obj.rrd_id >= _RRD_BASE
    )


async def test_the_walk_never_holds_more_than_one_page() -> None:
    """Live row objects stay bounded by the page size, not by the window.

    This is the whole point of the rewrite. Four pages of four rows: an
    accumulating client would have 16 rows alive by the end, a streaming one at
    most 4 — the page the generator is suspended on.
    """
    pages = [[_row(page * _PAGE + i) for i in range(_PAGE)] for page in range(4)]
    client = _client(_paged_transport(pages))
    consumed = 0
    high_water = 0

    async with client:
        async for page in client.iter_report_pages(
            date_from=date(2026, 7, 13), date_to=date(2026, 7, 19)
        ):
            consumed += len(page)
            assert len(page) <= _PAGE
            # Release the caller's own reference, so what is left alive is what
            # the generator itself is holding across the yield.
            del page
            high_water = max(high_water, _live_rows())

    assert consumed == 16
    assert high_water <= _PAGE


async def test_the_walk_stops_on_a_short_page_and_follows_the_cursor() -> None:
    """A page shorter than the limit ends the walk; each request resumes after it."""
    cursors: list[str] = []
    pages = [[_row(i) for i in range(_PAGE)], [_row(_PAGE + i) for i in range(2)]]
    remaining = list(pages)

    def handler(request: httpx.Request) -> httpx.Response:
        cursors.append(request.url.params["rrdid"])
        return httpx.Response(200, json=remaining.pop(0) if remaining else [])

    client = _client(httpx.MockTransport(handler))

    async with client:
        collected = [
            row
            async for page in client.iter_report_pages(
                date_from=date(2026, 7, 13), date_to=date(2026, 7, 19)
            )
            for row in page
        ]

    assert [row.rrd_id for row in collected] == [_RRD_BASE + i for i in range(_PAGE + 2)]
    # Two requests only — the short second page ends the walk without a probe
    # for a third.
    assert cursors == ["0", str(_RRD_BASE + _PAGE - 1)]


async def test_a_stalled_cursor_raises_instead_of_looping_forever() -> None:
    """A full page that does not advance `rrd_id` is a bug WB could ship any day."""
    page = [_row(i) for i in range(_PAGE)]
    client = _client(_paged_transport([page, page, page]))

    async def walk() -> None:
        """Drain the whole walk, so a stall would spin here forever."""
        async with client:
            async for _ in client.iter_report_pages(
                date_from=date(2026, 7, 13), date_to=date(2026, 7, 19)
            ):
                pass

    with pytest.raises(IntegrationError, match="pagination stalled"):
        await walk()


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
    from src.modules.finreports.tasks.settlement import _SpentToken

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
    from src.modules.finreports.tasks import settlement

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
        async def ingest_finance_report(self, pages: Any, **_kw: Any) -> int:
            written = 0
            async for page in pages:
                written += len(page)
            return written

    monkeypatch.setattr(settlement, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(settlement, "WBFinanceClient", lambda *a, **k: _Client())

    outcome = await settlement._ingest_one_streamed_page(
        tokens=SimpleNamespace(statistics="t", workspace_id=uuid.uuid4(), name="NEVA"),
        window_from=date(2026, 7, 9),
        window_to=date(2026, 8, 8),
        cursor=0,
        build_ingestion=lambda _s: _Ingestion(),
        gate=NullRateGate(),
    )

    assert outcome == (5, None)
    assert session.commits == len(batches), (
        f"committed {session.commits} times for {len(batches)} batches — the page "
        "is still one transaction"
    )
