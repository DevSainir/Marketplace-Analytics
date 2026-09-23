"""Walking a SPAN of settlement history, several reports to a request.

``POST /sales-reports/detailed`` takes a period rather than a report id and
serves every row inside it, across as many reports as fit a page. Measured on
«Демо» 2026-09-23: one request over 03.08-20.09 returned 40 910 rows and
all **8** reports — exactly the row set we hold for that window — and on NEVA the
mean report is 11 603 rows, so a 100 000-row page holds about eight of them.

That is the whole reason this module exists. A full history costs ~7 requests
here against 143 by report id on «Демо», and at one request a minute the
difference is an hour and a half of a new seller's first day.

**What it gives up, stated plainly.** By id, a report is either complete or it
is not, and the walk books each one the moment it finishes. Here the unit is the
window: a walk that dies part-way has committed rows for several reports and
finished none of them, so it books nothing and the whole window is re-fetched.
The rows are upserted by ``rrd_id``, so that costs requests and never
correctness — and it keeps the invariant that matters, which is that a header
means «all of this report is here».

**And the risk it takes.** A seller documented on WB's forum that ``rrdId`` is
not monotonic by date across report boundaries on this form, so a walk could
stop early and silently. Measured on «Демо» 2026-09-23 it did not: zero
descents across eight report boundaries, each report contiguous and in date
order, including one WB had served eight days late. That is one window on one
кабинет and does not cover re-issued or month-split reports — which is why every
report this walk books is checked against WB's own ``forPaySum`` afterwards
(`docs/finreports/PNL.md` has the arithmetic).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.endpoints import SALES_REPORTS_BY_PERIOD_PATH
from src.integrations.wildberries.rate_limit import finance_reports_rate_gate
from src.modules.finreports.tasks.settlement.page import _ingest_one_streamed_page
from src.modules.finreports.tasks.settlement.reports import (
    MissingReport,
    SettlementWalk,
    _book_report,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def walk_settlement_window(
    *,
    tokens: WorkspaceTokenBundle,
    reports: Sequence[MissingReport],
    build_ingestion: object,
    reserve_seconds: float = 0.0,
) -> SettlementWalk:
    """Fetch every report in ``reports`` as one paged walk over their span.

    The span is the whole stretch the reports cover, so reports we already hold
    that fall between them are fetched too. Their rows are upserted over
    identical values and their headers are left alone; the cost is bandwidth,
    and against a request a minute it is not close.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The reports to fetch, **each carrying WB's list entry** — the
            header is what gets booked, and a report without one cannot be
            certified by this walk. Order does not matter; the span does.
        build_ingestion: Factory taking a session and returning an
            ``IngestionService``.
        reserve_seconds: Non-zero marks this as background work that yields its
            window to anything a person is waiting on.

    Returns:
        A :class:`SettlementWalk`. ``windows_failed`` is 0 or 1 — the window is
        the unit here — and ``completed_through`` is the span's end once every
        page has landed, or ``None`` when any of them did not.
    """
    if not tokens.finance or not reports:
        return SettlementWalk(0, 0, None)

    span_from = min(_starts_at(report) for report in reports)
    span_to = max(report.date_to for report in reports)
    gate = finance_reports_rate_gate(settings, token=tokens.finance)
    rows = 0
    cursor = 0
    while True:
        try:
            # Outside the session, like every other settlement request: the
            # wait for WB's next token is a minute long and PostgreSQL closes a
            # transaction left idle for 300 s.
            await gate.acquire(SALES_REPORTS_BY_PERIOD_PATH, reserve_seconds=reserve_seconds)
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement window %s..%s for %s stopped — no rate token: %s",
                span_from,
                span_to,
                tokens.name,
                exc,
            )
            return SettlementWalk(rows, 1, None)
        page = await _ingest_one_streamed_page(
            tokens=tokens,
            period=(span_from, span_to),
            cursor=cursor,
            build_ingestion=build_ingestion,
            gate=gate,
        )
        # Added before the check: a request that died mid-body has already
        # committed whatever batches reached the database.
        rows += page.rows
        if not page.ok:
            return SettlementWalk(rows, 1, None)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    # Booked only now, and only because the whole span landed. Booking a report
    # the moment a LATER report's rows appeared would be reading `rrd_id` order
    # as date order — the very assumption this walk is not willing to make.
    for report in reports:
        await _book_report(report=report, tokens=tokens, build_ingestion=build_ingestion)
    logger.info(
        "finreports: settlement window %s..%s ingested %d rows over %d report(s) for %s.",
        span_from,
        span_to,
        rows,
        len(reports),
        tokens.name,
    )
    return SettlementWalk(rows, 0, span_to)


def _starts_at(report: MissingReport) -> date:
    """The first settlement day this report covers.

    From WB's list entry where there is one. A report with no header cannot be
    booked by this walk anyway, so its period is only ever used to widen the
    span, and ``date_to`` is the safe answer there — a span that starts too late
    would silently skip days, one that starts too early only costs rows.
    """
    return report.header.date_from if report.header is not None else report.date_to


__all__ = ["walk_settlement_window"]
