"""Fetching, committing and accounting for ONE page of settlement history.

One page per tick, because the page is the only unit WB's budget allows: it
serves this endpoint once per fifteen minutes per token and restarts that window
for anything asked inside it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.modules.finreports.tasks.backfill.span import (
    PNL_EMPTY_STOP,
    PNL_FLOOR_DAYS,
    _format_cursor,
    _parse_cursor,
    next_span,
)
from src.modules.finreports.tasks.settlement import _ingest_one_page
from src.modules.workspaces.contract import LaneStep, WorkspaceTokenBundle

logger = get_logger(__name__)

#: The endpoint the gate is keyed on.
SETTLEMENT_PATH = "/api/v5/supplier/reportDetailByPeriod"


async def advance_pnl(
    tokens: WorkspaceTokenBundle,
    *,
    cursor: str | None,
    settled_days: Sequence[date],
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
        cursor: Opaque resume point; ``None`` picks the next gap to fill.
        settled_days: Settlement days already stored for this workspace — the
            coverage the next span is chosen from.
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
        span_from, span_to, rrd_id, empties, search_from = _parse_cursor(cursor)
    else:
        search_from = today - timedelta(days=PNL_FLOOR_DAYS)
        chosen = next_span(settled_days, search_from=search_from, today=today)
        if chosen is None:
            return LaneStep(0, 0, None, True, "Вся история P&L собрана.")
        span_from, span_to = chosen
        rrd_id, empties = 0, 0

    total = max((span_to - span_from).days + 1, 1)
    if span_to < span_from:
        return LaneStep(total, total, None, True, "Вся история P&L собрана.")

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
            cursor=cursor or _format_cursor(span_from, span_to, rrd_id, empties, search_from),
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
            cursor=_format_cursor(span_from, span_to, rrd_id, empties, search_from),
            finished=False,
            message="Wildberries не отдал страницу — повторим через 15 минут.",
        )

    rows, next_cursor = outcome
    if next_cursor is None and rows == 0:
        # WB served NOTHING. That is the answer for an exhausted window and for
        # a window it is briefly not serving, and the two are indistinguishable
        # in one reply — so it takes PNL_EMPTY_STOP of them in a row, each a
        # separate fifteen-minute window, before the span is believed complete.
        empties += 1
        if empties < PNL_EMPTY_STOP:
            return LaneStep(
                done=None,
                total=total,
                cursor=_format_cursor(span_from, span_to, rrd_id, empties, search_from),
                finished=False,
                message=(
                    f"Wildberries вернул пусто ({empties} из {PNL_EMPTY_STOP}) — проверим ещё раз."
                ),
            )
        return LaneStep(total, total, None, True, "История P&L собрана.")
    if next_cursor is None:
        # A short but non-empty page: ordinary pagination, the window is done.
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
    true_start, covered = await _measure_progress(tokens, span_from, span_to, next_cursor)
    total = max((span_to - true_start).days + 1, 1)
    span_from = true_start
    return LaneStep(
        done=min(covered, total),
        total=total,
        cursor=_format_cursor(span_from, span_to, next_cursor, 0, search_from),
        finished=False,
        message=f"Собираем P&L: {min(covered, total)} из {total} дней.",
        rows=rows,
    )


async def _measure_progress(
    tokens: WorkspaceTokenBundle, span_from: date, span_to: date, next_cursor: int
) -> tuple[date, int]:
    """``(true_start, days_covered)`` for the span, read back from our tables.

    Both numbers come from the database rather than being tracked in the cursor:
    the page was just committed, so the rows themselves are the authority on
    what the walk achieved, and a cursor that also carried counters would be a
    second thing to keep in step with them.

    ``true_start`` is the oldest settlement day we now hold — the seller's real
    first report once the first page has landed. ``days_covered`` counts from
    there to the newest day the cursor has reached.

    Both halves are bounded to the SPAN, and the upper bound is not decoration.
    The forward harvest has been writing recent weeks all along, and those rows
    carry the highest ``rrd_id``s of all — so without `rr_dt <= span_to` the
    "newest day reached" is a day the backfill never walked to, and the lane
    reports 100% on its second page. Observed live 2026-09-11: NEVA read
    1033/1033 while still waiting for its next window.

    Args:
        tokens: The workspace being walked.
        span_from: The span start currently in the cursor, used as a fallback
            when the table is somehow empty.
        span_to: The span end — rows past it belong to the forward harvest,
            not to this walk.
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
                        LogisticsTransaction.rrd_id <= next_cursor,
                        LogisticsTransaction.rr_dt <= span_to,
                    ),
                ).where(
                    LogisticsTransaction.workspace_id == tokens.workspace_id,
                    LogisticsTransaction.rr_dt <= span_to,
                )
            )
        ).one()
    true_start, latest = row
    if true_start is None:
        return span_from, 0
    if latest is None or latest < true_start:
        return true_start, 0
    return true_start, (latest - true_start).days + 1
