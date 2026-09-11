"""The P&L lane: a new workspace's settlement history, one page per tick.

This is the slow lane and the reason the profile shows four of them rather than
one bar. WB serves ``reportDetailByPeriod`` **once per fifteen minutes per
token**, and a request made inside that block restarts it — so a large seller's
history is not a walk that can be hurried, only one that must not be wasted.

Two measurements shape it, both taken on prod 2026-09-09:

* **A wide window pages exactly like a narrow one.** One request for
  2024-01-01..2026-09-06 returned a full 10 000-row page spanning six weekly
  reports, ``rrd_id`` ascending. So the cost of a span is ``ceil(rows / limit)``
  requests, NOT one per week: 66 instead of ~140 for a 650 k-row account. The
  weekly split the forward harvest uses is a transaction constraint, not a WB
  one — and this lane has no such constraint, because it commits and exits
  between pages instead of holding one open across a fifteen-minute wait.
* **A 10 000-row page costs ~110 MB of RSS.** That is the entire reason this is
  one page per tick and not a loop: the peak is one page, and the process is
  gone before the next.

The span is fixed when the lane starts and carried in the cursor. It has to be:
the natural way to write this — "ask for everything older than the earliest row
I hold" — moves its own goalposts as it ingests, so the denominator shrinks each
tick and the bar walks backwards.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from celery import Task

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import _ingest_one_page
from src.modules.workspaces.contract import (
    BackfillLane,
    BackfillState,
    LaneStep,
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
    read_cursor,
    record_progress,
)

logger = get_logger(__name__)

#: How far back the lane is willing to ask. WB serves from the account's own
#: beginning, so this is only a bound on absurdity — five years is older than
#: any seller account we have seen, and the walk ends on a short page, not here.
PNL_FLOOR_DAYS = 5 * 365

#: Cursor field separator. The cursor carries the whole span, not just the page
#: pointer: see the module docstring for why recomputing the span per tick
#: makes the progress bar run backwards.
_SEP = "|"

#: The endpoint the gate is keyed on.
SETTLEMENT_PATH = "/api/v5/supplier/reportDetailByPeriod"

#: Seconds before the next page. WB's own budget on this endpoint — asking
#: sooner restarts its window and makes the lane slower, not faster.
_NEXT_PAGE_SECONDS = 15 * 60 + 30

#: A tick is one request plus one ingest; the limit is a hung-call backstop.
_TICK_SOFT_LIMIT_SECONDS = 5 * 60


def _parse_cursor(cursor: str) -> tuple[date, date, int]:
    """Read ``span_from|span_to|rrd_id`` back."""
    raw_from, raw_to, raw_rrdid = cursor.split(_SEP)
    return date.fromisoformat(raw_from), date.fromisoformat(raw_to), int(raw_rrdid)


def _format_cursor(span_from: date, span_to: date, rrd_id: int) -> str:
    """Write the span and page pointer into one opaque string."""
    return f"{span_from.isoformat()}{_SEP}{span_to.isoformat()}{_SEP}{rrd_id}"


def initial_span(*, earliest_held: date | None, today: date) -> tuple[date, date]:
    """The span a fresh P&L lane should walk.

    Everything from the floor up to the day before the oldest settlement day we
    already hold — so a workspace whose forward harvest has been running for
    weeks backfills only what is genuinely missing behind it, and one that has
    never harvested walks the lot.

    A gap in the MIDDLE of what we hold is deliberately not this lane's problem;
    the daily reconcile pass re-reads behind the watermark for that.

    Args:
        earliest_held: Oldest ``rr_dt`` already stored for the workspace.
        today: Today in Moscow time.

    Returns:
        The inclusive ``(from, to)`` span.
    """
    span_from = today - timedelta(days=PNL_FLOOR_DAYS)
    span_to = (earliest_held - timedelta(days=1)) if earliest_held else today - timedelta(days=1)
    return span_from, span_to


async def advance_pnl(
    tokens: WorkspaceTokenBundle,
    *,
    cursor: str | None,
    earliest_held: date | None,
    build_ingestion: object,
) -> LaneStep:
    """Fetch, commit and account for ONE page of settlement history.

    Takes its rate token before opening any transaction — the gate that WAITS
    rather than the one that refuses, because at one request per fifteen
    minutes the wait IS the work. The page itself is then ingested by the same
    primitive the forward harvest uses, so a backfilled row and a harvested one
    are written by identical code.

    Args:
        tokens: The workspace's decrypted WB credentials.
        cursor: Opaque resume point; ``None`` starts a new span.
        earliest_held: Oldest ``rr_dt`` already stored — used only when
            starting, to decide where the span ends.
        build_ingestion: Factory taking a session and returning an
            ``IngestionService``, injected the same way the walk takes it.

    Returns:
        The step's outcome. A short page means WB has served the whole span, so
        the lane is finished; progress is measured in settlement DAYS covered,
        which is the only unit knowable before the walk starts.
    """
    if not tokens.statistics:
        return LaneStep(0, 0, None, True, "Нет токена «Статистика» — P&L пропущен.")

    today = moscow_today()
    if cursor:
        span_from, span_to, rrd_id = _parse_cursor(cursor)
    else:
        span_from, span_to = initial_span(earliest_held=earliest_held, today=today)
        rrd_id = 0

    total = max((span_to - span_from).days + 1, 1)
    if span_to < span_from:
        return LaneStep(total, total, None, True, "Вся история P&L уже собрана.")

    # The gate that REFUSES, not the one that waits — and this is the whole
    # difference between a lane that runs and one that dies on its first tick.
    #
    # `settlement_walk_rate_gate` is built to QUEUE: the fleet walk takes its
    # token before opening a transaction, and there a quarter of an hour of
    # waiting is the correct behaviour. Inside a tick it is fatal. Measured in
    # production 2026-09-10: the lane's first tick asked at 18:00:04, the gate
    # answered "waiting 956.0s for a rate token", and Celery's 300 s soft limit
    # killed the task five minutes later with `SoftTimeLimitExceeded` — which is
    # not an `IntegrationError`, so the branch below never ran, no progress was
    # recorded, nothing re-enqueued, and a thirteen-hour walk ended silently on
    # its first step.
    #
    # A tick must never block on a budget it can re-enqueue against instead.
    gate = statistics_rate_gate(settings, token=tokens.statistics)
    try:
        await gate.acquire(SETTLEMENT_PATH)
    except IntegrationError as exc:
        # Not a failure: WB's window is simply still closed. The tick returns
        # unchanged and the task re-enqueues — asking anyway would restart the
        # block and cost the NEXT quarter of an hour too.
        logger.info(
            "finreports: P&L backfill for %s waiting on WB's window (%s).", tokens.name, exc
        )
        return LaneStep(
            done=None,
            total=total,
            cursor=cursor or _format_cursor(span_from, span_to, rrd_id),
            finished=False,
            message="Ждём окно Wildberries (1 запрос в 15 минут)…",
        )

    outcome = await _ingest_one_page(
        tokens=tokens,
        window_from=span_from,
        window_to=span_to,
        cursor=rrd_id,
        build_ingestion=build_ingestion,
        gate=gate,
    )
    if outcome is None:
        return LaneStep(
            done=None,
            total=total,
            cursor=_format_cursor(span_from, span_to, rrd_id),
            finished=False,
            message="Wildberries не отдал страницу — повторим через 15 минут.",
        )

    rows, next_cursor = outcome
    if next_cursor is None:
        return LaneStep(total, total, None, True, "История P&L собрана.", rows=rows)

    # Re-anchor the span on the seller's ACTUAL first settlement day, which the
    # first page has just revealed. The span starts at a five-year floor because
    # nothing knows the account's age before asking — but NEVA's first report is
    # 2024-07-11, so that floor put three empty years in the denominator and the
    # bar read 1078/1792 (60%) after a single page, then crawled. Measuring from
    # the oldest day we now hold makes the percentage mean what it looks like.
    #
    # `total_units` is documented as an estimate the lane may revise; this is
    # the revision it was written for.
    true_start, covered = await _measure_progress(tokens, span_from, next_cursor)
    total = max((span_to - true_start).days + 1, 1)
    span_from = true_start
    return LaneStep(
        done=min(covered, total),
        total=total,
        cursor=_format_cursor(span_from, span_to, next_cursor),
        finished=False,
        message=f"Собираем P&L: {min(covered, total)} из {total} дней.",
        rows=rows,
    )


async def _measure_progress(
    tokens: WorkspaceTokenBundle, span_from: date, next_cursor: int
) -> tuple[date, int]:
    """``(true_start, days_covered)`` for the span, read back from our tables.

    Both numbers come from the database rather than being tracked in the cursor:
    the page was just committed, so the rows themselves are the authority on
    what the walk achieved, and a cursor that also carried counters would be a
    second thing to keep in step with them.

    ``true_start`` is the oldest settlement day we now hold — the seller's real
    first report once the first page has landed. ``days_covered`` counts from
    there to the newest day the cursor has reached.

    Args:
        tokens: The workspace being walked.
        span_from: The span start currently in the cursor, used as a fallback
            when the table is somehow empty.
        next_cursor: The ``rrd_id`` the walk has reached.

    Returns:
        The re-anchored span start and the days covered from it.
    """
    from sqlalchemy import func, select

    from src.core.database import AsyncSessionLocal
    from src.modules.finreports.models import LogisticsTransaction

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(
                    func.min(LogisticsTransaction.rr_dt),
                    func.max(LogisticsTransaction.rr_dt).filter(
                        LogisticsTransaction.rrd_id <= next_cursor
                    ),
                ).where(LogisticsTransaction.workspace_id == tokens.workspace_id)
            )
        ).one()
    true_start, latest = row
    if true_start is None:
        return span_from, 0
    if latest is None or latest < true_start:
        return true_start, 0
    return true_start, (latest - true_start).days + 1


@celery_app.task(  # type: ignore[untyped-decorator]
    name="finreports.backfill_pnl",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
)
def backfill_pnl(self: Task[object, object], workspace_id: str) -> dict[str, object]:
    """Fetch ONE page of settlement history, then queue the next in ~15 minutes.

    The countdown is the endpoint's own budget, not a guess: WB serves this
    once per fifteen minutes per token and RESTARTS the window for anything
    asked inside it, so a tighter re-enqueue would make the lane slower rather
    than faster. A tick that finds the window still shut records that it is
    waiting and re-queues without spending a request.

    Deliberately no ``autoretry_for``: on this endpoint a retry ladder is
    actively harmful for the same reason. A failed page is retried by the next
    scheduled tick — and a tick that never gets scheduled because the task died
    outright is what ``workspaces.sweep_stalled_backfills`` exists to catch.
    """

    async def _run() -> dict[str, object]:
        ws_id = uuid.UUID(workspace_id)
        async with AsyncSessionLocal() as session:
            tokens = await load_workspace_token_bundle(session, ws_id)
        if tokens is None:
            raise IntegrationError(f"Workspace {workspace_id} no longer exists; P&L aborted.")
        bind_workspace(ws_id)

        cursor = await read_cursor(workspace_id=ws_id, lane=BackfillLane.PNL)
        earliest = await _earliest_held(ws_id)
        step = await advance_pnl(
            tokens,
            cursor=cursor,
            earliest_held=earliest,
            build_ingestion=build_ingestion,
        )
        await record_progress(
            workspace_id=ws_id,
            lane=BackfillLane.PNL,
            state=BackfillState.DONE if step.finished else BackfillState.RUNNING,
            done_units=step.done,
            total_units=step.total,
            cursor=step.cursor,
            message=step.message,
        )
        if not step.finished:
            celery_app.send_task(
                "finreports.backfill_pnl",
                kwargs={"workspace_id": workspace_id},
                countdown=_NEXT_PAGE_SECONDS,
            )
        logger.info(
            "backfill pnl for %s: %s/%d days, rows=%d, finished=%s",
            workspace_id,
            step.done,
            step.total,
            step.rows,
            step.finished,
        )
        return {"done": step.done, "total": step.total, "rows": step.rows}

    return run_task(_run())


async def _earliest_held(workspace_id: uuid.UUID) -> date | None:
    """The oldest settlement day already stored for this workspace."""
    from sqlalchemy import func, select

    from src.modules.finreports.models import LogisticsTransaction

    async with AsyncSessionLocal() as session:
        stmt = select(func.min(LogisticsTransaction.rr_dt)).where(
            LogisticsTransaction.workspace_id == workspace_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()
