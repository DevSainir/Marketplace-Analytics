"""Which reports one tick fetches, and by which of WB's two methods.

Split from :mod:`walk`, which keeps what a tick RECORDS. The choice here is the
expensive one, and both halves of it were learned in production:

* **A window may only span a RUN.** It is addressed by period, so it fetches
  every row in its span — twelve scattered reports span most of a seller's
  history, and the extra is pages rather than bandwidth. A scattered backlog
  walks report by report, which is what scatter costs.
* **A run too wide for one tick is paused, not abandoned.** NEVA sat on a
  300 000-row window it re-fetched from zero every sweep; the walk now hands
  back its ``rrdId`` and the next tick continues the same span.

Neither walk reserves. On a bucket of one token a minute with a 240 s cap, a
caller that will not touch a token until it has sat free for 120 s is not
yielding a window — it is refusing its own request. The ordering that was for
lives one level up: the lane stands aside while the harvest holds its lock.
"""

from __future__ import annotations

import time

from src.core.logging import get_logger
from src.integrations.wildberries.rate_limit.surfaces import FINANCE_QUEUE_SECONDS
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.tasks.backfill.discovery import InFlight
from src.modules.finreports.tasks.settlement import (
    MissingReport,
    walk_settlement_reports,
    walk_settlement_window,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Most reports one tick will fetch. Reports are walked one after another, each
#: in a session that closes before the next begins, so memory does not bound
#: this; time does, and that is :data:`_TICK_WORK_BUDGET_SECONDS`. This is the
#: belt to its braces.
REPORTS_PER_TICK = 12

#: The history tick's soft time limit. Defined here, beside the budget that has
#: to fit inside it, and used by the task in the package's ``__init__``.
TICK_SOFT_LIMIT_SECONDS = 15 * 60

#: Longest page measured: 217 s, at WB's 100 000-row limit. Rounded up.
_PAGE_SECONDS_MAX = 240

#: What a tick spends before its first page: the list request, which waits for
#: its own one-a-minute token, and writing WB's totals onto held reports.
_TICK_PREAMBLE_SECONDS = 120

#: How long a tick keeps taking on new work — the last moment a new page or
#: report may start.
#:
#: Derived rather than chosen, because the deadline cannot stop work already
#: begun. A page that starts at the deadline still waits for its token — up to
#: ``FINANCE_QUEUE_SECONDS`` — and then runs up to ``_PAGE_SECONDS_MAX``, after
#: a preamble the deadline did not see. It was ten minutes until 2026-09-24, and
#: 600 + 240 + 217 is past the 900 s soft limit. Overrunning that limit is not a
#: slow tick but a silent one: `SoftTimeLimitExceeded` is not the
#: `IntegrationError` the lane catches, so nothing is recorded and nothing
#: re-enqueued.
_TICK_WORK_BUDGET_SECONDS = (
    TICK_SOFT_LIMIT_SECONDS - FINANCE_QUEUE_SECONDS - _PAGE_SECONDS_MAX - _TICK_PREAMBLE_SECONDS
)


def _contiguous_run(
    due: tuple[MissingReport, ...], *, listed: tuple[WBFinanceReportHeader, ...]
) -> tuple[MissingReport, ...]:
    """The newest unbroken run of owed reports, at most a tick's worth.

    A window is addressed by PERIOD, so it fetches every row in its span —
    including reports we already hold that happen to fall inside it. Taking the
    twelve newest owed reports and spanning them sounds equivalent and is not:
    once the backlog is scattered, twelve reports can span most of a seller's
    history, and the extra is not bandwidth but PAGES, which are the thing WB
    rates.

    Measured on NEVA 2026-09-24, which is how this was found. With fifteen
    reports left, scattered, the span reached across the archive, the walk ran
    past the task's 900 s soft limit, and the tick died to
    `SoftTimeLimitExceeded` — which the lane does not catch, so it recorded
    nothing and re-enqueued nothing, sixteen hours into a fill that should have
    taken minutes.

    So the window is only ever a RUN: consecutive in WB's own ordering, with
    nothing held in between. A scattered backlog then walks report by report,
    which is what a scattered backlog costs.

    Args:
        due: Reports owed, newest first.
        listed: Every report WB named, held or not — the ordering «consecutive»
            is measured in.

    Returns:
        The run, newest first, capped at :data:`REPORTS_PER_TICK`. Empty only
        when ``due`` is.
    """
    if not due:
        return ()
    order = {
        header.report_id: index
        for index, header in enumerate(sorted(listed, key=lambda h: h.date_to, reverse=True))
    }
    run = [due[0]]
    for report in due[1:REPORTS_PER_TICK]:
        previous, current = order.get(run[-1].report_id), order.get(report.report_id)
        if previous is None or current is None or current != previous + 1:
            break
        run.append(report)
    return tuple(report for report in run if report.header is not None)


def _resumed_run(
    in_flight: InFlight, *, listed: tuple[WBFinanceReportHeader, ...]
) -> tuple[MissingReport, ...]:
    """The reports an open window covers, rebuilt from its stored span.

    From the LISTING rather than from the backlog, because a window half-walked
    has already written rows for some of its reports — they may no longer look
    owed, and dropping them would leave the window booking a subset of what it
    fetched.

    Args:
        in_flight: The window a previous tick left open.
        listed: Every report WB named.

    Returns:
        The reports inside the span, newest first.
    """
    return tuple(
        MissingReport(report_id=header.report_id, date_to=header.date_to, header=header)
        for header in sorted(listed, key=lambda h: h.date_to, reverse=True)
        if in_flight.span_from <= header.date_to <= in_flight.span_to
    )


async def fetch_batch(
    *,
    tokens: WorkspaceTokenBundle,
    due: tuple[MissingReport, ...],
    listed: tuple[WBFinanceReportHeader, ...],
    in_flight: InFlight | None,
    build_ingestion: object,
) -> tuple[tuple[MissingReport, ...], int, int, InFlight | None]:
    """Fetch as many of the owed reports as this tick has time for.

    Two walks, chosen by how much is owed.

    **More than one report: one paged walk over their span.** WB serves the same
    rows by period, several reports to a page — ~21 on «Демо», ~8 on NEVA —
    so a history that costs 143 requests one report at a time costs about seven
    this way. The window is then the unit: it books nothing unless the whole
    span landed, and a failure re-fetches all of it. Rows are upserted by
    ``rrd_id``, so that costs requests and never correctness.

    **A single report: one request for that id.** A window of one would fetch
    the same rows and give up the per-report atomicity for nothing.

    The deadline only guards the second path. A window is one paged walk whose
    length the tick cannot predict from the report count, and cutting it short
    would throw away every page it had paid for; the per-report loop can stop
    between reports and keep everything it has.

    Args:
        tokens: The workspace's decrypted WB credentials.
        due: The reports this sweep may take, newest first.
        listed: Every report WB named, which is what «contiguous» is measured
            against — a run with a report we already HOLD in the middle of it
            is not one run but two.
        build_ingestion: Factory taking a session and returning an
            ``IngestionService``.

    Returns:
        ``(attempted, rows, failed)``. ``attempted`` is what the ceiling moves
        past — the reports left behind by the deadline stay above it and are
        offered again on the next tick, unchanged.
    """
    # Newest first, all the way down. The old lane had to sort a batch the other
    # way because `walk_settlement_reports` certifies the unbroken PREFIX of
    # what it is handed, and a descending batch would have certified a gap in
    # front of itself. Handing it one report at a time makes that rule trivially
    # true and gives the direction back to the seller: a tick cut short by the
    # deadline below leaves them this month rather than the archive.
    # A window a previous tick left open comes first and alone. Its rows are
    # half-fetched and its span is a fact about the run that started it, so
    # re-deriving the run now — from a backlog those rows have not yet changed —
    # would abandon them.
    run = (
        _resumed_run(in_flight, listed=listed) if in_flight else _contiguous_run(due, listed=listed)
    )
    if len(run) > 1:
        # A RUN of owed reports with WB's list entry for each: one paged walk
        # over their span, which is where the 8-21x lives. See
        # `settlement.window` for what the window gives up in exchange.
        walk = await walk_settlement_window(
            tokens=tokens,
            reports=run,
            build_ingestion=build_ingestion,
            # Never a reserving acquire, here or below. The reserve makes a
            # caller wait for a token free for 120 s, and `acquire` accumulates
            # that wait across pages: a second page asked for 360 s against a
            # 240 s cap and the window was discarded with 100 000 rows already
            # committed (NEVA, 2026-09-23). Ordering against the harvest is the
            # harvest lock's job, which this lane stands aside for explicitly.
            cursor=in_flight.cursor if in_flight else 0,
            deadline=time.monotonic() + _TICK_WORK_BUDGET_SECONDS,
        )
        if walk.next_cursor is not None:
            # Out of tick with the window still open. Nothing attempted,
            # nothing booked, and the span goes back into the cursor so the
            # next tick continues it instead of starting over — which is what
            # threw away 300 000 rows a tick on NEVA, every sweep, 2026-09-24.
            span_from = min(
                report.header.date_from if report.header else report.date_to for report in run
            )
            span_to = max(report.date_to for report in run)
            return (), walk.rows, 0, InFlight(span_from, span_to, walk.next_cursor)
        # Finished or failed, and either way every report in the span was
        # attempted: the ceiling moves past them and a failure comes back on the
        # next sweep, exactly as it does for a single report.
        return run, walk.rows, 0 if walk.ok else len(run), None

    # Not a run, so report by report — which is what a scattered backlog costs.
    batch = due[:REPORTS_PER_TICK]
    deadline = time.monotonic() + _TICK_WORK_BUDGET_SECONDS
    attempted: list[MissingReport] = []
    rows = 0
    failed = 0
    for report in batch:
        if attempted and time.monotonic() >= deadline:
            logger.info(
                "finreports: P&L backfill for %s stopping at %d of %d reports — out of tick.",
                tokens.name,
                len(attempted),
                len(batch),
            )
            break
        by_id = await walk_settlement_reports(
            tokens=tokens,
            reports=(report,),
            build_ingestion=build_ingestion,
        )
        attempted.append(report)
        rows += by_id.rows
        failed += by_id.windows_failed
    return tuple(attempted), rows, failed, None


__all__ = ["REPORTS_PER_TICK", "fetch_batch"]
