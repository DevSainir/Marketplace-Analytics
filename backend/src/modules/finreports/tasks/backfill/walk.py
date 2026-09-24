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
from src.modules.finreports.tasks.backfill.batch import fetch_batch
from src.modules.finreports.tasks.backfill.discovery import (
    WB_REPORTS_EPOCH,
    Backlog,
    advance_ceiling,
    format_cursor,
    parse_cursor,
    survey_backlog,
)
from src.modules.finreports.tasks.harvest.ledger import record_wb_totals
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
    ceiling, sweep, at_sweep_start, in_flight = resumed or (today, 1, 0, None)

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
            cursor=format_cursor(ceiling, sweep, at_sweep_start, in_flight),
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
            cursor=format_cursor(ceiling, sweep, at_sweep_start, in_flight),
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

    attempted, rows, failed, still_open = await fetch_batch(
        tokens=tokens,
        due=backlog.due,
        listed=backlog.listed,
        in_flight=in_flight,
        build_ingestion=build_ingestion,
    )
    done = min(backlog.done + len(attempted) - failed, backlog.total)
    # The ceiling may only pass reports this tick FINISHED with. A window still
    # open has not been attempted — its reports are owed, its rows are half
    # there, and moving past it would leave the next sweep to start it again
    # from nothing.
    moved = advance_ceiling(attempted, ceiling) if still_open is None else ceiling
    return LaneStep(
        done=done,
        total=backlog.total,
        cursor=format_cursor(moved, sweep, at_sweep_start or backlog.outstanding, still_open),
        finished=False,
        message=(
            f"Собираем окно: {rows} строк…"
            if still_open is not None
            else f"Собираем историю P&L: {done} из {backlog.total} отчётов."
        ),
        rows=rows,
    )


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
