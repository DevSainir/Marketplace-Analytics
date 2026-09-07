"""Walking WB's settlement report one week at a time.

The report is the P&L's only source, and WB serves it under the tightest budget
of any surface we touch: measured live on 2026-09-07, `reportDetailByPeriod`
answers with `x-ratelimit-limit: 1` and `x-ratelimit-reset: 917` — **one request
per quarter of an hour, per seller token** — and a request made while the bucket
is empty RESTARTS that window rather than queueing behind it.

That single fact rules out the shape this walk used to have. It asked for a
rolling 28-day window and paged through it by `rrdid` inside one open
transaction, which works for exactly as long as the whole window fits in one
page. The first seller it did not fit (2026-09-07, 241 SKUs) got its second page
answered with a 429, and the retry that honoured WB's demanded 897 s wait sat
inside the transaction until PostgreSQL closed the connection under it.

So the window is now split at the grain WB itself publishes on: **one week per
request**, each week its own transaction.

* **A week per window, and one REQUEST per page of it.** WB forms one
  realization report a week, so a week is the natural window — but a week is
  not automatically one page: the first seller measured (2026-09-07) has weeks
  past the 10 000-row page limit, and a second page is a second quarter-hour.
  So the walk paces itself per page, not per week.
* **The wait happens with no transaction open.** The token for each page is
  taken before the session exists, so a fifteen-minute wait costs wall-clock
  and nothing else. Inside the transaction the walk holds a gate it has already
  paid, precisely so it cannot wait there.
* **Each page commits on its own.** All-or-nothing cannot span a wait longer
  than PostgreSQL will hold a transaction, so it is the page that is atomic
  now, not the week. That is safe because every row is upserted by `rrd_id`
  and the report header is written with the page it came in on: a week left
  half-loaded is completed by the next tick, whose span starts at the last
  settled day. What must never happen — a page torn in half — still cannot,
  under the SAVEPOINT each one runs in.
* **An incomplete week is reported, not inferred.** A window whose walk stops
  early is counted, and the harvest turns that count into a failed source.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceClient
from src.integrations.wildberries.endpoints import SETTLEMENT_REPORT_PATH
from src.integrations.wildberries.rate_limit import RateGate, settlement_walk_rate_gate
from src.integrations.wildberries.schemas import WBReportDetailRow
from src.modules.finreports.services import IngestionService
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Days per settlement window. WB forms one realization report a week, so a
#: week is both the natural unit of the data and — under a one-request budget —
#: the largest window we can be confident fits a single page.
WINDOW_DAYS = 7

#: Retry ladder for one window's pages. The walk still pages inside an open
#: transaction, and PostgreSQL closes an idle one after 300 s: one retry bounds
#: a page at ~80 s (a 30 s timeout, 20 s of backoff, another 30 s timeout). The
#: 429 this ladder used to fight is now prevented by the gate rather than
#: survived, so there is nothing left for a second retry to win.
MAX_RETRIES = 1


def settlement_windows(*, date_from: date, date_to: date) -> list[tuple[date, date]]:
    """Split an inclusive settlement span into consecutive ≤7-day windows.

    Oldest first, so a backfill that runs out of time or budget has covered the
    early weeks and left the recent ones — the opposite order would leave gaps
    behind the last settled day, and the next run's window starts from that day.

    Args:
        date_from: Inclusive first settlement day.
        date_to: Inclusive last settlement day.

    Returns:
        The windows to ask WB for, or an empty list when the span is inverted
        (which is what "nothing to harvest" looks like once every day is
        covered).
    """
    windows: list[tuple[date, date]] = []
    cursor = date_from
    while cursor <= date_to:
        window_end = min(cursor + timedelta(days=WINDOW_DAYS - 1), date_to)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return windows


async def walk_settlement_windows(
    *,
    tokens: WorkspaceTokenBundle,
    date_from: date,
    date_to: date,
    build_ingestion: object,
) -> tuple[int, int]:
    """Harvest one workspace's settlement span, a week per request.

    Args:
        tokens: The workspace's decrypted WB credentials.
        date_from: Inclusive first settlement day to cover.
        date_to: Inclusive last settlement day to cover.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService` — injected rather than imported so this
            module does not reach back into the harvest that calls it.

    Returns:
        ``(rows, windows_failed)``. A non-zero second element means the span is
        only partly covered: those weeks are missing from the P&L until a later
        tick, whose window starts from the last settled day and so asks again.
    """
    if not tokens.statistics:
        return 0, 0

    windows = settlement_windows(date_from=date_from, date_to=date_to)
    gate = settlement_walk_rate_gate(settings, token=tokens.statistics)
    rows = 0
    failed = 0
    for window_from, window_to in windows:
        window_rows, complete = await _harvest_window(
            tokens=tokens,
            window_from=window_from,
            window_to=window_to,
            gate=gate,
            build_ingestion=build_ingestion,
        )
        rows += window_rows
        if not complete:
            failed += 1
    if failed:
        logger.error(
            "finreports: settlement incomplete for %s — %d of %d weeks stopped early "
            "(%s..%s); the P&L is short those days until a later tick asks again.",
            tokens.name,
            failed,
            len(windows),
            date_from,
            date_to,
        )
    return rows, failed


async def _harvest_window(
    *,
    tokens: WorkspaceTokenBundle,
    window_from: date,
    window_to: date,
    gate: RateGate,
    build_ingestion: object,
) -> tuple[int, bool]:
    """Harvest one week, a page per request, and say whether it finished.

    Args:
        tokens: The workspace's decrypted WB credentials.
        window_from: Inclusive first settlement day of this week.
        window_to: Inclusive last settlement day of this week.
        gate: The walk's rate gate. A token is taken per PAGE, and always
            before the page's session is opened.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService`.

    Returns:
        ``(rows, complete)``. ``complete`` is False when WB withheld a page or
        the walk ran out of rate budget part-way — the rows already committed
        stay committed, and the week's remainder falls to a later tick.
    """
    rows = 0
    cursor = 0
    while True:
        try:
            # Outside the session, and this is the whole point: the wait for
            # WB's next token is minutes long, and PostgreSQL closes a
            # transaction left idle for 300 s.
            await gate.acquire(SETTLEMENT_REPORT_PATH)
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement %s..%s for %s stopped — no rate token: %s",
                window_from,
                window_to,
                tokens.name,
                exc,
            )
            return rows, False
        page = await _ingest_one_page(
            tokens=tokens,
            window_from=window_from,
            window_to=window_to,
            cursor=cursor,
            build_ingestion=build_ingestion,
        )
        if page is None:
            return rows, False
        page_rows, next_cursor = page
        rows += page_rows
        if next_cursor is None:
            logger.info(
                "finreports: settlement %s..%s ingested %d rows for %s.",
                window_from,
                window_to,
                rows,
                tokens.name,
            )
            return rows, True
        cursor = next_cursor


async def _ingest_one_page(
    *,
    tokens: WorkspaceTokenBundle,
    window_from: date,
    window_to: date,
    cursor: int,
    build_ingestion: object,
) -> tuple[int, int | None] | None:
    """Fetch one page, commit it, and report where the walk stands.

    The page is streamed into the transaction rather than collected first: a
    settlement row costs ~9.7 KB while it is being validated, and holding more
    than a page is what OOM-killed the 2026-08-11 harvest. The SAVEPOINT keeps
    the page all-or-nothing.

    The client is handed a gate whose token this page has already taken — a
    second acquire here would wait out another full refill, inside the very
    transaction the outer wait exists to protect.

    Returns:
        ``(rows, next_cursor)`` with ``next_cursor`` ``None`` when this was the
        window's last page, or ``None`` when WB withheld the page.
    """
    async with AsyncSessionLocal() as session:
        ingestion: IngestionService = build_ingestion(session)  # type: ignore[operator]
        try:
            async with (
                session.begin_nested(),
                WBFinanceClient(
                    settings,
                    token=tokens.statistics,
                    max_retries=MAX_RETRIES,
                    rate_gate=_SpentToken(),
                ) as client,
            ):
                page = await client.fetch_report_page(
                    date_from=window_from, date_to=window_to, cursor=cursor
                )
                page_limit = client.page_limit
                rows = await ingestion.ingest_finance_report(
                    _one_page(page), workspace_id=tokens.workspace_id
                )
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement %s..%s failed for %s: %s",
                window_from,
                window_to,
                tokens.name,
                exc,
            )
            return None
        await session.commit()
    # A short page is the last one. A full page whose cursor does not advance
    # would loop forever asking WB the same question every fifteen minutes, so
    # it ends the window instead.
    if len(page) < page_limit:
        return rows, None
    next_cursor = page[-1].rrd_id
    if next_cursor <= cursor:
        logger.error(
            "finreports: settlement %s..%s for %s stalled — a full page did not advance "
            "rrd_id past %d.",
            window_from,
            window_to,
            tokens.name,
            cursor,
        )
        return rows, None
    return rows, next_cursor


async def _one_page(
    page: list[WBReportDetailRow],
) -> AsyncGenerator[list[WBReportDetailRow], None]:
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
    """

    async def acquire(self, endpoint: str) -> None:
        """Let the request through — its token was taken before the session."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Ignore WB's remaining-budget header.

        The shared bucket is corrected by every other caller of this endpoint,
        and a second page inside this window would otherwise clamp it to zero
        after the walk had already paid for the page it is reading.
        """
        return


__all__ = ["MAX_RETRIES", "WINDOW_DAYS", "settlement_windows", "walk_settlement_windows"]
