"""Fetching, committing and accounting for the history this workspace lacks.

The unit of work is a ``reportId``, and that is the whole of this rewrite. It
used to be a page of a date span, because the endpoint took a period and a
period is not a report — so the lane carried a span, a page cursor, an
empty-answer streak and a search ceiling, and every one of those was a thing
that could be stale in a way nobody would notice. WB now names the reports and
serves each one whole, so the lane asks "which ids am I missing" and fetches
them.

Three consequences, all deletions:

* **A short page no longer ends a span**, because there are no spans. A report
  is either fully ingested or it is not, and :func:`walk_settlement_reports`
  already knows which.
* **An empty answer is no longer ambiguous.** ``PNL_EMPTY_STOP`` existed because
  WB answered an exhausted window and a window it was briefly not serving with
  the same ``204``, and believing the first one cost NEVA two years of P&L. The
  list says outright which reports exist; a fetch that brings nothing back is
  not evidence about the history's shape.
* **Progress is counted in reports rather than days**, so the walk no longer
  queries its own tables to find out how far it has got. ``_measure_progress``
  and both of its bounds — each of which was a production bug once — go with it.

What survives is the rate discipline, because none of it was about addressing:
the token is taken before the session exists, the page is streamed, each batch
commits as it lands, and the walk never blocks on a budget it could re-enqueue
against instead.
"""

from __future__ import annotations

import time
from datetime import date

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_DETAILED_PATH,
    SALES_REPORTS_LIST_PATH,
)
from src.integrations.wildberries.rate_limit import finance_reports_rate_gate
from src.integrations.wildberries.rate_limit.surfaces import BACKGROUND_RESERVE_SECONDS
from src.modules.finreports.tasks.backfill.discovery import (
    WB_REPORTS_EPOCH,
    Backlog,
    advance_ceiling,
    format_cursor,
    parse_cursor,
    survey_backlog,
)
from src.modules.finreports.tasks.harvest.ledger import record_wb_totals
from src.modules.finreports.tasks.settlement import (
    MissingReport,
    walk_settlement_reports,
    walk_settlement_window,
)
from src.modules.workspaces.contract import LaneStep, WorkspaceTokenBundle

logger = get_logger(__name__)

#: Most reports one tick will fetch.
#:
#: One per tick was the old shape, for a reason that has expired: a page cost a
#: quarter of an hour of WB's budget and ~110 MB of RSS, so a tick that looped
#: would have held a worker slot for most of an hour to no purpose.
#:
#: At one request a minute the loop is where the throughput is. A tick's own
#: overhead is a re-enqueue plus the gap the countdown leaves — and the
#: countdown is read from a bucket the tick has just emptied, with the
#: background reserve on top, so one report per tick costs roughly three
#: minutes per report against a budget that allows one. Batching moves the
#: waiting inside the tick, where it is spent on the next report instead of on
#: nothing.
#:
#: Memory does not bound this: reports are walked one after another, each into
#: its own session which closes before the next begins, so the peak is one
#: report's batches whether a tick walks one or twelve. Time does, and that is
#: :data:`_TICK_WORK_BUDGET_SECONDS` below; this is the belt to its braces.
REPORTS_PER_TICK = 12

#: How long a tick keeps taking on new reports.
#:
#: Ten minutes against the task's fifteen-minute soft limit, so the report in
#: flight when the budget runs out has five minutes to finish — more than twice
#: the longest page measured (217 s, at 100 000 rows; the largest report on
#: «Демо» is 16 801). Overrunning the soft limit is not a slow tick but a
#: silent one: `SoftTimeLimitExceeded` is not the `IntegrationError` the lane
#: catches, so nothing would be recorded and nothing re-enqueued.
#:
#: Checked BETWEEN reports and never inside one. A report is the unit that can
#: be left for the next tick; a half-fetched one is not, and abandoning it would
#: throw away the rate token it had already paid for.
_TICK_WORK_BUDGET_SECONDS = 10 * 60

#: The longest standing refusal a tick will sit through rather than re-enqueue.
#:
#: Sized to tell WB's ordinary pacing apart from WB's punishment, which on this
#: surface are two orders of magnitude apart: an empty 1/min bucket reports at
#: most 60 s, while a penalty block reports hundreds or thousands. Anything past
#: this is not a wait, it is a closed door.
#:
#: Checked BEFORE anything is sent, and that is the point: ``acquire`` SLEEPS
#: out whatever it is told to wait, up to ``FINANCE_QUEUE_SECONDS``, and only
#: then raises. Both figures are inside this task's soft limit today, and this
#: is the belt to that braces — a tick that dies to
#: ``SoftTimeLimitExceeded`` records nothing and re-enqueues nothing, because it
#: is not the ``IntegrationError`` the lane catches. That is precisely how this
#: lane was lost for eleven hours on 2026-09-10, on the endpoint before this
#: one, where the queue was 1000 s against a 300 s limit.
_TICK_WAIT_BUDGET_SECONDS = 120.0


async def advance_pnl(
    tokens: WorkspaceTokenBundle,
    *,
    cursor: str | None,
    build_ingestion: object,
) -> LaneStep:
    """Fetch the next reports this workspace is missing, and account for them.

    Args:
        tokens: The workspace's decrypted WB credentials.
        cursor: Opaque resume point; ``None`` starts a fresh sweep at today.
        build_ingestion: Factory taking a session and returning an
            ``IngestionService``, injected the same way the forward walk takes
            it, so a backfilled row and a harvested one are written by identical
            code.

    Returns:
        The step's outcome, measured in REPORTS. ``total`` is zero whenever this
        tick learned nothing about the denominator — a refused list — and the
        caller reads that as "leave the bar alone" rather than as an estimate of
        zero.
    """
    if not tokens.finance:
        return LaneStep(0, 0, None, True, "Нет токена «Финансы» — P&L пропущен.")

    today = moscow_today()
    floor = WB_REPORTS_EPOCH
    resumed = parse_cursor(cursor) if cursor else None
    ceiling, sweep, at_sweep_start = resumed or (today, 1, 0)

    shut_for = await _shut_for(tokens.finance)
    if shut_for > _TICK_WAIT_BUDGET_SECONDS:
        logger.info(
            "finreports: P&L backfill for %s waiting on WB's window (%.0fs).",
            tokens.name,
            shut_for,
        )
        return LaneStep(
            done=None,
            total=0,
            cursor=format_cursor(ceiling, sweep, at_sweep_start),
            finished=False,
            message="Ждём окно Wildberries…",
        )

    try:
        backlog = await survey_backlog(tokens=tokens, floor=floor, ceiling=ceiling, today=today)
    except IntegrationError as exc:
        # Not a failure of the walk: WB did not answer the cheap question. The
        # tick returns unchanged and the task re-enqueues.
        logger.warning(
            "finreports: report list failed for %s — the P&L backfill waits: %s",
            tokens.name,
            exc,
        )
        return LaneStep(
            done=None,
            total=0,
            cursor=format_cursor(ceiling, sweep, at_sweep_start),
            finished=False,
            message="Wildberries не отдал список отчётов — повторим.",
        )

    # WB's own per-report totals, onto every report we already hold. Free — the
    # list is already in hand — and this lane is the only caller that sees the
    # WHOLE history: the forward harvest lists 45 days, so without this the
    # archive's totals could never be filled. An UPDATE, so a report WB lists
    # and we have not taken cannot be created here and counted as held.
    await record_wb_totals(workspace_id=tokens.workspace_id, listed=backlog.listed)

    if not backlog.due:
        return _end_of_sweep(backlog, sweep=sweep, at_sweep_start=at_sweep_start, today=today)

    attempted, rows, failed = await _fetch_batch(
        tokens=tokens, due=backlog.due, build_ingestion=build_ingestion
    )
    done = min(backlog.done + len(attempted) - failed, backlog.total)
    return LaneStep(
        done=done,
        total=backlog.total,
        cursor=format_cursor(
            advance_ceiling(attempted, ceiling), sweep, at_sweep_start or backlog.outstanding
        ),
        finished=False,
        message=f"Собираем историю P&L: {done} из {backlog.total} отчётов.",
        rows=rows,
    )


async def _fetch_batch(
    *,
    tokens: WorkspaceTokenBundle,
    due: tuple[MissingReport, ...],
    build_ingestion: object,
) -> tuple[tuple[MissingReport, ...], int, int]:
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
    batch = due[:REPORTS_PER_TICK]
    bookable = tuple(report for report in batch if report.header is not None)
    if len(bookable) > 1:
        # Several reports owed and WB's list entry for each: one paged walk over
        # their whole span, which is where the 8-21x lives. See
        # `settlement.window` for what the window gives up in exchange.
        walk = await walk_settlement_window(
            tokens=tokens,
            reports=bookable,
            build_ingestion=build_ingestion,
            # No reserve here, unlike the by-id walk below, and the difference
            # is not politeness — it is whether a window of more than one page
            # can run at all. The reserve makes a caller wait for a token free
            # for 120 s; `acquire` accumulates that wait across pages, so a
            # second page asked for 360 s against a 240 s cap and the whole
            # window was discarded with 100 000 rows already committed (NEVA,
            # 2026-09-23). It also protects nobody: the harvest and «Обновить»
            # spend `detailed/{id}` and `list`, never this bucket.
            reserve_seconds=0.0,
        )
        # Every report in the span was attempted, whether or not it landed — the
        # ceiling moves past all of them and a failure comes back on the next
        # sweep, exactly as it does for a single report.
        failed = len(bookable) if walk.windows_failed else 0
        return bookable, walk.rows, failed

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
        walk = await walk_settlement_reports(
            tokens=tokens,
            reports=(report,),
            build_ingestion=build_ingestion,
            reserve_seconds=BACKGROUND_RESERVE_SECONDS,
        )
        attempted.append(report)
        rows += walk.rows
        failed += walk.windows_failed
    return tuple(attempted), rows, failed


def _end_of_sweep(backlog: Backlog, *, sweep: int, at_sweep_start: int, today: date) -> LaneStep:
    """Decide what a sweep that has run off the bottom of the history means.

    Three endings, and the middle one is why sweeps exist at all.

    **Nothing outstanding** — every report WB has formed inside the depth is on
    file. The lane is done, and this is the ordinary ending.

    **Something outstanding, and fewer than when this sweep began** — the sweep
    achieved something, so the reports it missed are worth asking about again.
    The ceiling goes back to today and the lane walks down a second time. This
    is the retry path for a report lost to a timeout or a refused page: the
    ceiling moves past such a report within its own sweep (see
    :func:`advance_ceiling`), so without this it would be lost silently, which
    is the failure this subsystem has had most often and noticed latest.

    **Something outstanding, and no fewer than when this sweep began** — a whole
    pass changed nothing, and the lane stops rather than becoming a permanent
    1/min load on an endpoint that answers with penalty blocks.

    It says «забрать не удалось», not «Wildberries их не отдаёт», and the
    distinction was paid for. On NEVA 2026-09-23 a pass fetched over a hundred
    thousand rows and booked none of them — every window died on its second
    page — so the backlog did not move and the lane announced that WB was
    withholding 63 reports it had in fact served. A backlog that has not shrunk
    means this walk finished nothing; what WB will and will not serve is a claim
    this rule has no evidence for.

    Args:
        backlog: The survey this tick took.
        sweep: Which pass this is.
        at_sweep_start: Reports outstanding when the pass began; 0 when unknown,
            which only happens on a lane that never completed a first pass.
        today: Today in Moscow time — the ceiling a new pass starts from.

    Returns:
        The step's outcome.
    """
    outstanding, total, done = backlog.outstanding, backlog.total, backlog.done
    if outstanding == 0:
        return LaneStep(total, total, None, True, "История P&L собрана.")
    if at_sweep_start and outstanding >= at_sweep_start:
        logger.error(
            "finreports: P&L history gave up with %d report(s) unfetched after a full pass "
            "that changed nothing. WB lists them; we did not complete them. This is a walk "
            "that failed, not a seller with no data.",
            outstanding,
        )
        return LaneStep(
            done,
            total,
            None,
            True,
            f"История P&L собрана; {outstanding} отчётов забрать не удалось.",
        )
    return LaneStep(
        done=done,
        total=total,
        cursor=format_cursor(today, sweep + 1, outstanding),
        finished=False,
        message=f"Повторяем {outstanding} отчётов, которые не удалось забрать…",
    )


async def _shut_for(token: str) -> float:
    """Seconds WB has this workspace's report methods shut for, or 0.

    Both buckets, because a tick needs both and the one that is open does not
    make up for the one that is not. Read from Redis, so it costs no WB request
    and sends nothing.

    Args:
        token: The workspace's «Финансы» token — buckets are per seller account.

    Returns:
        The longer of the two refusals, or ``0.0`` when nothing stands in the
        way. Fails open: a bucket that cannot be read is not a block.
    """
    gate = finance_reports_rate_gate(settings, token=token)
    return max(
        await gate.retry_after(SALES_REPORTS_DETAILED_PATH),
        await gate.retry_after(SALES_REPORTS_LIST_PATH),
    )


__all__ = ["REPORTS_PER_TICK", "advance_pnl"]
