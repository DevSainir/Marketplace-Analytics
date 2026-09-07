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

* **A week is one request, not one page.** WB forms one realization report a
  week; a week of settlement rows fits inside a page for any seller we have
  seen, so the paging loop stays as the safety net rather than the mechanism.
* **The wait happens between weeks, with no transaction open.** The token is
  taken before the session exists (:func:`_take_token`), so a fifteen-minute
  wait costs wall-clock and nothing else. Inside the transaction the walk holds
  a gate it has already paid, precisely so it cannot wait there.
* **Each week commits on its own.** A backfill that dies in its third week
  keeps the first two, and the next tick resumes from what is now the last
  settled day. All-or-nothing still holds where it matters — within a week,
  under a SAVEPOINT — but it no longer spans a month of somebody's money.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceClient
from src.integrations.wildberries.endpoints import SETTLEMENT_REPORT_PATH
from src.integrations.wildberries.rate_limit import settlement_walk_rate_gate
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
        try:
            # Before the session exists. This is the whole point: the wait for
            # WB's next token is minutes long, and a transaction may not be
            # open across it.
            await gate.acquire(SETTLEMENT_REPORT_PATH)
        except IntegrationError as exc:
            failed += 1
            logger.warning(
                "finreports: settlement %s..%s for %s never got a rate token: %s",
                window_from,
                window_to,
                tokens.name,
                exc,
            )
            continue
        window_rows = await _harvest_window(
            tokens=tokens,
            window_from=window_from,
            window_to=window_to,
            build_ingestion=build_ingestion,
        )
        if window_rows is None:
            failed += 1
            continue
        rows += window_rows
    if failed:
        logger.error(
            "finreports: settlement incomplete for %s — %d of %d weeks failed (%s..%s); "
            "the P&L is missing those days until a later tick asks again.",
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
    build_ingestion: object,
) -> int | None:
    """Fetch and commit one week, or return ``None`` when WB withheld it.

    The pages are streamed into the transaction rather than collected first: a
    settlement row costs ~9.7 KB while it is being validated, and holding a
    whole window is what OOM-killed the 2026-08-11 harvest. A SAVEPOINT keeps
    the week all-or-nothing even so.

    The client is handed a gate whose token this window has already taken —
    a second acquire here would wait out another full refill, inside the very
    transaction the outer wait exists to protect.
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
                rows = await ingestion.ingest_finance_report(
                    client.iter_report_pages(date_from=window_from, date_to=window_to),
                    workspace_id=tokens.workspace_id,
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
    logger.info(
        "finreports: settlement %s..%s ingested %d rows for %s.",
        window_from,
        window_to,
        rows,
        tokens.name,
    )
    return rows


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
