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
from src.integrations.wildberries.rate_limit import settlement_walk_rate_gate
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

    gate = settlement_walk_rate_gate(settings, token=tokens.statistics)
    try:
        await gate.acquire("/api/v5/supplier/reportDetailByPeriod")
    except IntegrationError as exc:
        # Not a failure: WB's window is simply still closed. The tick returns
        # unchanged and the task re-enqueues — asking anyway would restart the
        # block and cost the NEXT quarter of an hour too.
        logger.info(
            "finreports: P&L backfill for %s waiting on WB's window (%s).", tokens.name, exc
        )
        return LaneStep(
            done=0,
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
            done=0,
            total=total,
            cursor=_format_cursor(span_from, span_to, rrd_id),
            finished=False,
            message="Wildberries не отдал страницу — повторим через 15 минут.",
        )

    rows, next_cursor = outcome
    if next_cursor is None:
        return LaneStep(total, total, None, True, "История P&L собрана.", rows=rows)

    # Progress is measured in settlement days rather than pages, because the
    # number of pages is not knowable until the last one arrives. It advances
    # unevenly — a busy month is several pages — which is honest: the bar
    # tracks the calendar it is filling, not our guess at the row count.
    covered = await _covered_days(tokens, span_from, next_cursor)
    return LaneStep(
        done=min(covered, total),
        total=total,
        cursor=_format_cursor(span_from, span_to, next_cursor),
        finished=False,
        message=f"Собираем P&L: {min(covered, total)} из {total} дней.",
        rows=rows,
    )


async def _covered_days(tokens: WorkspaceTokenBundle, span_from: date, next_cursor: int) -> int:
    """Settlement days of the span now stored, as the progress numerator.

    Read back from our own table rather than tracked in the cursor: the rows
    were just committed, so the database is the authority on what the walk has
    actually achieved, and a cursor that also carried a count would be a second
    thing to keep in step.
    """
    from sqlalchemy import func, select

    from src.core.database import AsyncSessionLocal
    from src.modules.finreports.models import LogisticsTransaction

    async with AsyncSessionLocal() as session:
        stmt = select(func.max(LogisticsTransaction.rr_dt)).where(
            LogisticsTransaction.workspace_id == tokens.workspace_id,
            LogisticsTransaction.rrd_id <= next_cursor,
        )
        latest = (await session.execute(stmt)).scalar_one_or_none()
    if latest is None:
        return 0
    return max((latest - span_from).days + 1, 0)


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
    scheduled tick, not by Celery.
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
            "backfill pnl for %s: %d/%d days, rows=%d, finished=%s",
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
