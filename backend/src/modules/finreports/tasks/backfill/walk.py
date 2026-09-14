"""Fetching, committing and accounting for ONE page of settlement history.

One page per tick, because the page is the only unit WB's budget allows: it
serves this endpoint once per fifteen minutes per token and restarts that window
for anything asked inside it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.integrations.wildberries.rate_limit.surfaces import BACKGROUND_RESERVE_SECONDS
from src.modules.finreports.tasks.backfill.span import (
    PNL_EMPTY_STOP,
    PNL_FLOOR_DAYS,
    _format_cursor,
    _parse_cursor,
    _roll_to_next_span,
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
        build_ingestion: Factory taking a session and returning an
            ``IngestionService``, injected the same way the walk takes it.

    Returns:
        The step's outcome. Progress is measured in settlement DAYS covered,
        which is the only unit knowable before the walk starts.

        A span ending — a short page, or enough empty answers to believe one —
        finishes the SPAN, never the lane. What follows is
        :func:`_roll_to_next_span`, because a seller's history is not one
        stretch: NEVA's began with three years that predate the account and
        continued past a 715-day hole, and a lane that returned ``finished``
        from either ending declared the whole history complete over the hole.
    """
    if not tokens.statistics:
        return LaneStep(0, 0, None, True, "Нет токена «Статистика» — P&L пропущен.")

    today = moscow_today()
    # The product's chosen depth, resolved once: every span decision in this
    # tick must use the same floor, or a roll could offer a span the opening
    # search had already ruled out of scope.
    floor = today - timedelta(days=PNL_FLOOR_DAYS)
    if cursor:
        span_from, span_to, rrd_id, empties, search_to = _parse_cursor(cursor)
    else:
        # A fresh lane has concluded nothing, so its ceiling is today: the
        # newest gap inside the depth is the first thing it asks for.
        search_to = today
        chosen = next_span(
            await read_settled_days(tokens.workspace_id),
            search_to=search_to,
            today=today,
            floor=floor,
        )
        if chosen is None:
            return LaneStep(0, 0, None, True, "Вся история P&L собрана.")
        span_from, span_to = chosen
        rrd_id, empties = 0, 0

    total = max((span_to - span_from).days + 1, 1)
    if span_to < span_from:
        return _roll_to_next_span(
            await read_settled_days(tokens.workspace_id),
            before=span_from,
            today=today,
            rows=0,
            floor=floor,
        )

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
        # Reserving, because this is the walk nobody is waiting on: it takes
        # a window only once the harvest and any «Обновить» have had theirs.
        await gate.acquire(SETTLEMENT_PATH, reserve_seconds=BACKGROUND_RESERVE_SECONDS)
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
            cursor=cursor or _format_cursor(span_from, span_to, rrd_id, empties, search_to),
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
            cursor=_format_cursor(span_from, span_to, rrd_id, empties, search_to),
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
                cursor=_format_cursor(span_from, span_to, rrd_id, empties, search_to),
                finished=False,
                message=(
                    f"Wildberries вернул пусто ({empties} из {PNL_EMPTY_STOP}) — проверим ещё раз."
                ),
            )
        return _roll_to_next_span(
            await read_settled_days(tokens.workspace_id),
            before=span_from,
            today=today,
            rows=0,
            floor=floor,
        )
    if next_cursor is None:
        # A short but non-empty page: ordinary pagination, this SPAN is done.
        return _roll_to_next_span(
            await read_settled_days(tokens.workspace_id),
            before=span_from,
            today=today,
            rows=rows,
            floor=floor,
        )

    # The span is its own denominator, and no longer needs re-anchoring. That
    # existed because the walk began at a five-year floor and nothing knew the
    # account's age, so the bar read 1078/1792 after one page; it re-anchored on
    # the oldest row held. Both causes are gone — the depth is three months and a
    # span is at most one chunk — and keeping it would now be a BUG: the oldest
    # row a seller holds is years older than the chunk being walked, so the
    # re-anchor would stretch a 31-day span back across the whole archive and
    # take the cursor's span boundary with it.
    covered = await _measure_progress(tokens, span_from, span_to, next_cursor)
    return LaneStep(
        done=min(covered, total),
        total=total,
        cursor=_format_cursor(span_from, span_to, next_cursor, 0, search_to),
        finished=False,
        message=f"Собираем P&L: {min(covered, total)} из {total} дней.",
        rows=rows,
    )


async def _measure_progress(
    tokens: WorkspaceTokenBundle, span_from: date, span_to: date, next_cursor: int
) -> int:
    """How many days of THIS span the walk has covered, read back from our tables.

    The number comes from the rows rather than from the cursor: the page was
    just committed, so the table is the authority on what the walk achieved, and
    a cursor that also carried counters would be a second thing to keep in step
    with them.

    Bounded to the span at BOTH ends, and neither bound is decoration. The
    forward harvest has been writing recent weeks all along and those rows carry
    the highest ``rrd_id``s of all, so without ``rr_dt <= span_to`` the "newest
    day reached" is a day this walk never visited and the lane reports 100% on
    its second page — observed live 2026-09-11, NEVA reading 1033/1033 while
    still waiting for a window. And with the walk now taking the NEWEST span
    first, rows older than ``span_from`` are a different span's work entirely:
    counting them would have a 31-day chunk reporting centuries of progress.

    Args:
        tokens: The workspace being walked.
        span_from: The first day of the span being walked.
        span_to: The last day of the span being walked.
        next_cursor: The ``rrd_id`` the walk has reached.

    Returns:
        Days of the span covered so far, from ``span_from``.
    """
    from sqlalchemy import func, select

    from src.core.database import AsyncSessionLocal
    from src.modules.finreports.models import LogisticsTransaction

    async with AsyncSessionLocal() as session:
        latest = (
            await session.execute(
                select(func.max(LogisticsTransaction.rr_dt)).where(
                    LogisticsTransaction.workspace_id == tokens.workspace_id,
                    LogisticsTransaction.rrd_id <= next_cursor,
                    LogisticsTransaction.rr_dt >= span_from,
                    LogisticsTransaction.rr_dt <= span_to,
                )
            )
        ).scalar_one_or_none()
    if latest is None:
        return 0
    return (latest - span_from).days + 1


async def read_settled_days(workspace_id: uuid.UUID) -> list[date]:
    """Every distinct settlement day already stored for this workspace.

    The coverage a span is chosen from. Read HERE rather than handed in by the
    task, and that placement is the fix: the caller reads once per tick, before
    the page is fetched, so a span ending that consulted the caller's copy would
    be choosing what to do next from a picture taken before the rows it had just
    committed existed — and would offer back the hole it had that moment filled.

    One indexed DISTINCT over a few hundred rows per workspace. Cheap enough to
    read again after a commit, which is the only way the walk notices its own
    progress.
    """
    from sqlalchemy import distinct, select

    from src.core.database import AsyncSessionLocal
    from src.modules.finreports.models import LogisticsTransaction

    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(distinct(LogisticsTransaction.rr_dt))
            .where(
                LogisticsTransaction.workspace_id == workspace_id,
                LogisticsTransaction.rr_dt.is_not(None),
            )
            .order_by(LogisticsTransaction.rr_dt)
        )
        return [day for (day,) in rows.all() if day is not None]
