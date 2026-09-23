"""Walking WB's settlement report, one report per request.

The source moved on 2026-09-22. `GET /api/v5/supplier/reportDetailByPeriod`
was announced for shutdown on 15.07.2026 and is gone from WB's documentation;
`POST /api/finance/v1/sales-reports/detailed/{reportId}` replaces it at **one
request per minute** against the old endpoint's one per ~917 s. See
``docs/finreports/MIGRATION_TO_FINANCE_V1.md``.

That changed the unit of work, and the change is a simplification rather than
a port. The old endpoint took a PERIOD, so the walk cut a span into ≤7-day
windows because a week was roughly one report's worth — and then had to carry
«which window stopped early», a date prefix, and the possibility of a window
half-covering a report. Here the report id IS the unit: WB names the reports,
we fetch the ones we do not hold, and a report is either complete or it is
not.

What survives unchanged, because all of it was about the body rather than the
addressing:

* **A page per request, and the page is streamed.** WB allows 100 000 rows and
  decoding them whole is ~1.25 GB against a 768 MiB worker. Parsing as the
  body arrives moves the ceiling from the page to the batch.
* **The wait happens with no transaction open.** The token is taken before the
  session exists, because PostgreSQL closes a transaction left idle for 300 s.
* **Each batch commits as it lands.** One transaction over a whole page held
  fifty batches of statement state and OOM-killed the worker on 2026-09-15.
  Safe because every row is upserted by ``rrd_id`` and the cursor only
  advances on success.
* **The walk certifies only its unbroken prefix.** A later report succeeding
  must never certify a gap in front of it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from datetime import date
from typing import NamedTuple

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceReportsClient
from src.integrations.wildberries.endpoints import SALES_REPORTS_DETAILED_PATH
from src.integrations.wildberries.rate_limit import RateGate, finance_reports_rate_gate
from src.integrations.wildberries.schemas import WBFinanceReportRow
from src.modules.finreports.services import IngestionService
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Days per settlement window. WB forms one realization report a week, so a
#: week is both the natural unit of the data and — under a one-request budget —
#: survived, so there is nothing left for a second retry to win.
MAX_RETRIES = 1


class _Page(NamedTuple):
    """What one request to WB achieved.

    Attributes:
        rows: Rows COMMITTED by this request — including the batches a request
            that died part-way had already written. Counting only the requests
            that finished would under-report `harvest_rows_processed_total`,
            the one metric that answers "did this harvest do anything", by
            exactly the rows that are hardest to notice are missing.
        next_cursor: ``rrdid`` to resume from, or ``None`` when this was the
            window's last request.
        ok: False when WB withheld the body or died part-way through it. The
            rows above still stand — they are committed and upserted by
            ``rrd_id`` — but the window is not finished and must be re-asked.
    """

    rows: int
    next_cursor: int | None
    ok: bool


class SettlementWalk(NamedTuple):
    """What one workspace's settlement walk achieved.

    Attributes:
        rows: Settlement rows ingested across every report.
        windows_failed: Reports that stopped early — WB withheld a page, or the
            walk ran out of rate budget part-way. Still named for windows
            because it is what the harvest reports as a failed source and the
            alert joins on that name.
        completed_through: ``date_to`` of the last report in the **unbroken
            prefix** of completed ones, or ``None`` when the first stopped
            early. A high-water date cannot describe a gap, so it must never
            be handed out with one behind it.
    """

    rows: int
    windows_failed: int
    completed_through: date | None


#: How one page of settlement rows is written.
#:
#: The walk's machinery — a rate token taken outside the session, a page
#: streamed rather than decoded, a commit per batch, a cursor that only advances
#: on success — is the same for both lanes, and all of it was expensive to get
#: right. The only thing that differs is whether the report HEADER is written
#: alongside the rows, so that is the one thing passed in.
SettlementIngest = Callable[
    [IngestionService, AsyncGenerator[list[WBFinanceReportRow], None], uuid.UUID],
    Awaitable[int],
]


async def ingest_with_headers(
    ingestion: IngestionService,
    pages: AsyncGenerator[list[WBFinanceReportRow], None],
    workspace_id: uuid.UUID,
) -> int:
    """Write rows and their weekly report headers — the settled history."""
    return await ingestion.ingest_finance_report(pages, workspace_id=workspace_id)


async def ingest_rows_only(
    ingestion: IngestionService,
    pages: AsyncGenerator[list[WBFinanceReportRow], None],
    workspace_id: uuid.UUID,
) -> int:
    """Write rows alone — the provisional daily tail, which books itself.

    See
    :meth:`~src.modules.finreports.services.ingestion.service.IngestionService.ingest_settlement_rows`
    for why a daily header must not reach ``financial_report``.
    """
    return await ingestion.ingest_settlement_rows(pages, workspace_id=workspace_id)


class MissingReport(NamedTuple):
    """A report WB has formed that this workspace does not hold.

    Attributes:
        report_id: WB's own ``reportId`` — the walk's unit of work.
        date_to: Last settlement day the report covers, which is what moves
            the watermark once the report is complete.
    """

    report_id: int
    date_to: date


async def walk_settlement_reports(
    *,
    tokens: WorkspaceTokenBundle,
    reports: Sequence[MissingReport],
    build_ingestion: object,
    ingest: SettlementIngest = ingest_with_headers,
    reserve_seconds: float = 0.0,
) -> SettlementWalk:
    """Fetch every report this workspace is missing, one request per page.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The reports to fetch, **oldest first**. The order is what the
            prefix rule below means; a caller that shuffles them would
            certify a gap.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService` — injected rather than imported so this
            module does not reach back into the harvest that calls it.
        ingest: How a page is written. Defaults to the settled history's
            rows-and-headers write; the provisional daily lane passes
            :func:`ingest_rows_only`. See :data:`SettlementIngest`.
        reserve_seconds: Non-zero marks this walk as background work, which will
            not take a token that has been free for less than that. The history
            backfill passes it so a seller's fresh report is never queued behind
            months nobody is waiting for; the forward harvest leaves it at zero
            because it IS that fresh report.

    Returns:
        A :class:`SettlementWalk`. ``completed_through`` stops at the **first**
        report that did not finish, so a later one that happened to succeed
        can never certify the ones before it.
    """
    if not tokens.finance:
        return SettlementWalk(0, 0, None)

    gate = finance_reports_rate_gate(settings, token=tokens.finance)
    rows = 0
    failed = 0
    completed_through: date | None = None
    prefix_intact = True
    for report in reports:
        report_rows, complete = await _harvest_report(
            tokens=tokens,
            report=report,
            gate=gate,
            build_ingestion=build_ingestion,
            ingest=ingest,
            reserve_seconds=reserve_seconds,
        )
        rows += report_rows
        if complete:
            if prefix_intact:
                completed_through = report.date_to
        else:
            failed += 1
            prefix_intact = False
    if failed:
        logger.error(
            "finreports: settlement incomplete for %s — %d of %d report(s) stopped early; "
            "the P&L is short those days until a later tick asks again.",
            tokens.name,
            failed,
            len(reports),
        )
    return SettlementWalk(rows, failed, completed_through)


async def _harvest_report(
    *,
    tokens: WorkspaceTokenBundle,
    report: MissingReport,
    gate: RateGate,
    build_ingestion: object,
    ingest: SettlementIngest,
    reserve_seconds: float = 0.0,
) -> tuple[int, bool]:
    """Harvest one report, a page per request, and say whether it finished.

    Args:
        tokens: The workspace's decrypted WB credentials.
        report: The report to fetch.
        gate: The walk's rate gate. A token is taken per PAGE, and always
            before the page's session is opened.
        reserve_seconds: Yield this much of every window to callers a person is
            waiting on — see :func:`walk_settlement_reports`.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService`.
        ingest: How a page is written — see :data:`SettlementIngest`.

    Returns:
        ``(rows, complete)``. ``complete`` is False when WB withheld a page or
        the walk ran out of rate budget part-way — the rows already committed
        stay committed, and the remainder falls to a later tick.
    """
    rows = 0
    cursor = 0
    while True:
        try:
            # Outside the session, and this is the whole point: the wait for
            # WB's next token is a minute long, and PostgreSQL closes a
            # transaction left idle for 300 s.
            await gate.acquire(SALES_REPORTS_DETAILED_PATH, reserve_seconds=reserve_seconds)
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement report %d for %s stopped — no rate token: %s",
                report.report_id,
                tokens.name,
                exc,
            )
            return rows, False
        page = await _ingest_one_streamed_page(
            tokens=tokens,
            report_id=report.report_id,
            cursor=cursor,
            build_ingestion=build_ingestion,
            gate=gate,
            ingest=ingest,
        )
        # Added before the check, never inside it: a request that died mid-body
        # has already committed whatever batches reached the database, and those
        # rows are as real as any other.
        rows += page.rows
        if not page.ok:
            return rows, False
        if page.next_cursor is None:
            logger.info(
                "finreports: settlement report %d (through %s) ingested %d rows for %s.",
                report.report_id,
                report.date_to,
                rows,
                tokens.name,
            )
            return rows, True
        cursor = page.next_cursor


async def _ingest_one_streamed_page(
    *,
    tokens: WorkspaceTokenBundle,
    report_id: int,
    cursor: int,
    build_ingestion: object,
    gate: RateGate,
    ingest: SettlementIngest = ingest_with_headers,
) -> _Page:
    """Fetch one request's worth of settlement rows by streaming, and commit it.

    The only way a page is read, since 2026-09-17. It replaced a buffered one
    that decoded the whole response first, and therefore could only ask for as
    many rows as the worker's heap would hold — 10 000, measured at ~125 MB.
    This one parses the body as it arrives and ingests it in batches, so the
    ceiling is the batch and WB's own maximum of 100 000 becomes affordable.

    On an endpoint serving roughly four requests an hour that is the whole
    schedule rather than an efficiency: NEVA's remaining backfill was 33 requests
    at 10 000 rows and 4 at 100 000. The hourly tick kept the buffered path for
    two days longer than the backfill did, which is how it came to ask for a
    week it could not afford to decode on a worker already at 500 MB.

    The ``rrd_id`` of the last row is tracked as batches go past, because the
    walk's cursor must survive a body no caller ever held in one piece.

    **Each batch is committed as it lands.** Holding the whole page in one
    transaction put back the ceiling the streaming had just removed — bounded
    parsing, unbounded uncommitted state — and it showed: SIGKILL at 100 000
    rows. The caller's contract is unchanged, because a partially committed page
    reports failure, keeps its cursor, and is re-fetched into the same upsert.

    Returns:
        A :class:`_Page`. Its ``rows`` are what reached the database, which on
        a failed request is not zero.
    """
    total = 0
    last_rrd_id: int | None = None
    async with AsyncSessionLocal() as session:
        ingestion: IngestionService = build_ingestion(session)  # type: ignore[operator]
        try:
            async with WBFinanceReportsClient(
                settings,
                token=tokens.finance,
                max_retries=MAX_RETRIES,
                rate_gate=_SpentToken(gate),
            ) as client:
                stream_limit = client.stream_limit
                pages = client.stream_report_rows(report_id=report_id, cursor=cursor)
                async for batch in pages:
                    if not batch:
                        continue
                    last_rrd_id = batch[-1].rrd_id
                    total += await ingest(ingestion, _one_page(batch), tokens.workspace_id)
                    # Committed per batch, not per page. A single transaction
                    # over 100 000 rows held fifty batches' worth of statement
                    # state at once and OOM-killed the worker on 2026-09-15
                    # (SIGKILL, anon-rss 417 MB against a 768 MiB cap) — the
                    # streaming bounded what we PARSE at a time while leaving
                    # what we had not yet committed growing with the page.
                    #
                    # Per-page atomicity is not load-bearing here and never was:
                    # the walk resumes from an `rrdid` cursor it only advances
                    # on success, and the ingest is an upsert, so a page that
                    # dies half-committed is re-fetched and rewritten with the
                    # same result. What it buys is that a 217-second page is no
                    # longer 217 seconds of work to lose.
                    await session.commit()
                    del batch
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement report %d failed for %s: %s",
                report_id,
                tokens.name,
                exc,
            )
            return _Page(total, None, ok=False)
    # Fewer rows than we asked for means WB has served the window to its end.
    if total < stream_limit or last_rrd_id is None:
        return _Page(total, None, ok=True)
    if last_rrd_id <= cursor:
        logger.error(
            "finreports: settlement report %d for %s stalled — a full page did "
            "not advance rrd_id past %d.",
            report_id,
            tokens.name,
            cursor,
        )
        return _Page(total, None, ok=True)
    return _Page(total, last_rrd_id, ok=True)


async def _one_page(
    page: list[WBFinanceReportRow],
) -> AsyncGenerator[list[WBFinanceReportRow], None]:
    """Adapt a single page to the paginated shape the ingestion consumes."""
    if page:
        yield page


class _SpentToken:
    """A gate for a request whose token was already taken, outside this session.

    Not :class:`~src.integrations.wildberries.rate_limit.NullRateGate`, which
    reads as "this surface is unpaced". This one says the opposite: the surface
    is paced so tightly that the pacing had to happen somewhere the caller could
    afford to wait, and passing the real gate here would charge the same request
    twice.

    It withholds the budget HEADER from the shared bucket and forwards a
    PENALTY BLOCK to it, which is not an inconsistency: the header describes a
    window this page has already paid for, while the block describes a window
    nobody may enter. Swallowing the block here would leave the walk — the one
    caller that actually collected the 429s of 2026-09-09 — teaching the shared
    bucket nothing at all.
    """

    def __init__(self, shared: RateGate) -> None:
        """Wrap the walk's real gate.

        Args:
            shared: The gate holding this endpoint's cross-process bucket, to
                which a penalty block is forwarded.
        """
        self._shared = shared

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        """Let the request through — its token was taken before the session."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Ignore WB's remaining-budget header.

        The shared bucket is corrected by every other caller of this endpoint,
        and a second page inside this window would otherwise clamp it to zero
        after the walk had already paid for the page it is reading.
        """
        return

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Forward WB's stated block to the bucket every process shares."""
        await self._shared.penalise(endpoint, seconds)

    async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        """Ask the shared bucket, which is the one that knows.

        Forwarded rather than answered with 0: this wrapper says "my token is
        already paid for", not "this endpoint is open". Anyone asking how long
        the endpoint stays shut wants the shared bucket's answer.
        """
        return await self._shared.retry_after(endpoint)


__all__ = [
    "MAX_RETRIES",
    "MissingReport",
    "SettlementIngest",
    "SettlementWalk",
    "ingest_rows_only",
    "ingest_with_headers",
    "walk_settlement_reports",
]
