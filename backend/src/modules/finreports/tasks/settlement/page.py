"""Fetching and committing ONE request's worth of settlement rows.

The primitive both walks are built on, and the only part of this package that
knows what a WB response looks like. Everything expensive to get right lives
here rather than in either caller:

* **A page per request, and the page is streamed.** WB allows 100 000 rows and
  decoding them whole is ~1.25 GB against a 768 MiB worker. Parsing as the body
  arrives moves the ceiling from the page to the batch.
* **The wait happens with no transaction open.** The token is taken by the
  caller before the session exists, because PostgreSQL closes a transaction
  left idle for 300 s.
* **Each batch commits as it lands.** One transaction over a whole page held
  fifty batches of statement state and OOM-killed the worker on 2026-09-15.
  Safe because every row is upserted by ``rrd_id`` and the cursor only advances
  on success.

It takes EITHER a report id or a period, because WB serves the same rows both
ways and the two walks above it differ in nothing else. See
:mod:`~src.modules.finreports.tasks.settlement.window` for why a caller would
choose the period.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from typing import NamedTuple

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceReportsClient
from src.integrations.wildberries.rate_limit import RateGate
from src.integrations.wildberries.schemas import WBFinanceReportRow
from src.modules.finreports.services import IngestionService
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Retries inside one request. One, because a refused page means WB's window is
#: shut and a ladder against it walks straight back into the refusal.
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


async def _ingest_one_streamed_page(
    *,
    tokens: WorkspaceTokenBundle,
    report_id: int = 0,
    period: tuple[date, date] | None = None,
    cursor: int,
    build_ingestion: object,
    gate: RateGate,
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
                # The report id and the period address the same rows; which one
                # a caller passes is the difference between the two walks above.
                pages = (
                    client.stream_rows_by_period(
                        date_from=period[0], date_to=period[1], cursor=cursor
                    )
                    if period is not None
                    else client.stream_report_rows(report_id=report_id, cursor=cursor)
                )
                async for batch in pages:
                    if not batch:
                        continue
                    last_rrd_id = batch[-1].rrd_id
                    total += await ingestion.ingest_settlement_rows(
                        _one_page(batch), workspace_id=tokens.workspace_id
                    )
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
                "finreports: settlement %s failed for %s: %s",
                period or report_id,
                tokens.name,
                exc,
            )
            return _Page(total, None, ok=False)
    # Fewer rows than we asked for means WB has served the window to its end.
    if total < stream_limit or last_rrd_id is None:
        return _Page(total, None, ok=True)
    if last_rrd_id <= cursor:
        logger.error(
            "finreports: settlement %s for %s stalled — a full page did not "
            "advance rrd_id past %d.",
            period or report_id,
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


__all__ = ["MAX_RETRIES", "_Page", "_ingest_one_streamed_page"]
