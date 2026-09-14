"""The P&L lane: a new workspace's settlement history, one page per tick.

This is the slow lane and the reason the profile shows four of them rather than
one bar. WB serves ``reportDetailByPeriod`` **once per fifteen minutes per
token**, and a request made inside that block restarts it — so a large seller's
history is not a walk that can be hurried, only one that must not be wasted.

Three measurements shape it, all taken on prod:

* **A wide window pages exactly like a narrow one** (2026-09-09). One request
  over 980 days returned a full 10 000-row page spanning six weekly reports, so
  the cost of a span is ``ceil(rows / limit)`` requests, not one per week.
* **A 10 000-row page costs ~110 MB of RSS** — which is why this is one page per
  tick and not a loop.
* **An empty answer is not an ending** (2026-09-11). WB answers an exhausted
  window and a window it is briefly not serving with the same `204`, and
  believing the first one cost NEVA two years of P&L.

Split three ways by responsibility: :mod:`span` chooses what to walk and how to
resume, :mod:`walk` fetches and commits one page, and this module is the Celery
entrypoint that pays for a death being recorded.
"""

from __future__ import annotations

import uuid

from celery import Task

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.tasks import run_task
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.integrations.wildberries.rate_limit.surfaces import SETTLEMENT_PACE_CEILING_SECONDS
from src.modules.finreports.constants import HARVEST_LOCK_KEY
from src.modules.finreports.tasks.backfill.span import (
    PNL_EMPTY_STOP,
    PNL_FLOOR_DAYS,
    PNL_GAP_TOLERANCE_DAYS,
    SETTLEMENT_PATH,
    _format_cursor,
    _parse_cursor,
    next_span,
)
from src.modules.finreports.tasks.backfill.walk import advance_pnl
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.workspaces.contract import (
    BackfillLane,
    BackfillState,
    claim_chain,
    load_workspace_token_bundle,
    read_cursor,
    record_failure,
    record_progress,
)

logger = get_logger(__name__)

#: The floor on the gap between pages: WB's published budget for this endpoint.
_NEXT_PAGE_SECONDS = 15 * 60 + 30

#: Added to whatever the bucket reports, so a tick wakes just AFTER the window
#: opens rather than in the same second and losing the race to rounding.
_WAKE_MARGIN_SECONDS = 20


async def _next_page_delay(token: str) -> int:
    """When to ask for the next page — WB's number rather than a guess.

    This was briefly a LEARNED value, widening 1.5x on every refused page and
    easing 0.9x on every served one, and it was a mistake. It could not tell
    "WB punished us for asking too early" from "somebody else took the window",
    so ordinary contention — the hourly harvest, a one-off probe — ratcheted it
    upward, while successes were too rare to ease it back. Measured 2026-09-14
    it had pinned at 5400 s: one page every ninety minutes on an endpoint that
    serves four an hour, a six-fold self-inflicted slowdown.

    The bucket already knew the answer. It absorbs WB's own
    ``x-ratelimit-retry`` through ``penalise``, so ``retry_after`` reports
    exactly how long the endpoint stays shut — 890 s on a fresh 429, zero while
    a window is open — and does it without spending a token to find out. That is
    both simpler and better informed than anything this lane can infer from
    whether its last page arrived.

    Clamped at both ends: never faster than WB's published budget, never slower
    than the watchdog's patience is sized for.
    """
    gate = statistics_rate_gate(settings, token=token)
    shut_for = await gate.retry_after(SETTLEMENT_PATH)
    return min(
        max(_NEXT_PAGE_SECONDS, int(shut_for) + _WAKE_MARGIN_SECONDS),
        SETTLEMENT_PACE_CEILING_SECONDS,
    )


#: A tick is one request plus one ingest; the limit is a hung-call backstop.
_TICK_SOFT_LIMIT_SECONDS = 5 * 60

#: How long to stand aside when the forward harvest holds the settlement token.
#:
#: Just over the harvest's own lock TTL, so a yielding tick wakes to a token the
#: harvest has finished with rather than to the same closed door.
_YIELD_SECONDS = 11 * 60


async def _harvest_is_running() -> bool:
    """Whether the forward finance harvest currently holds its lock.

    The two walks share one token on an endpoint WB serves about four times an
    hour, and they are not equally urgent. The harvest collects the report WB
    published this morning — what the seller opens the app to see. The backfill
    fills history that has been missing for months and will still be there in
    fifteen minutes. Whoever asks first wins the window, so without this the
    ordering is luck: on 2026-09-14 the harvest happened to take 09:54 and the
    backfill's next tick was refused, which is the right outcome by accident.

    The monitoring lanes have obeyed the same rule against their own harvest
    from the start; this is the settlement lane catching up.

    A Redis failure answers ``False``. A backfill running while Redis is down is
    a smaller problem than a backfill that stops for good because it could not
    ask — and the rate gate still stands between it and WB either way.
    """
    try:
        return bool(await get_redis().exists(HARVEST_LOCK_KEY))
    except Exception:
        logger.warning("Could not read the finance harvest lock; assuming it is free.")
        return False


@celery_app.task(  # type: ignore[untyped-decorator]
    name="finreports.backfill_pnl",
    bind=True,
    soft_time_limit=_TICK_SOFT_LIMIT_SECONDS,
    time_limit=_TICK_SOFT_LIMIT_SECONDS + 60,
)
def backfill_pnl(
    self: Task[object, object], workspace_id: str, chain: str | None = None
) -> dict[str, object]:
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

    Args:
        workspace_id: The workspace being walked.
        chain: The token of the tick chain this one continues. ``None`` starts a
            fresh chain and supersedes any other — which is what every caller
            that is not the previous tick wants, and what keeps a watchdog
            restart from running alongside the lane it was restarting.
    """

    async def _run() -> dict[str, object]:
        ws_id = uuid.UUID(workspace_id)
        token = await claim_chain(ws_id, BackfillLane.PNL, chain)
        if token is None:
            logger.info(
                "backfill pnl for %s: superseded by a newer chain; this tick stops here.",
                workspace_id,
            )
            return {"superseded": True}
        async with AsyncSessionLocal() as session:
            tokens = await load_workspace_token_bundle(session, ws_id)
        if tokens is None:
            raise IntegrationError(f"Workspace {workspace_id} no longer exists; P&L aborted.")
        bind_workspace(ws_id)

        if await _harvest_is_running():
            # Stand aside without spending a request: the fresh report comes
            # first, and asking now would take the window it needs.
            await record_progress(
                workspace_id=ws_id,
                lane=BackfillLane.PNL,
                message="Ждём загрузку свежего отчёта…",
            )
            celery_app.send_task(
                "finreports.backfill_pnl",
                kwargs={"workspace_id": workspace_id, "chain": token},
                countdown=_YIELD_SECONDS,
            )
            logger.info("backfill pnl for %s yielded to the finance harvest.", workspace_id)
            return {"yielded": True}

        cursor = await read_cursor(workspace_id=ws_id, lane=BackfillLane.PNL)
        step = await advance_pnl(tokens, cursor=cursor, build_ingestion=build_ingestion)
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
            countdown = (
                await _next_page_delay(tokens.statistics)
                if tokens.statistics
                else _NEXT_PAGE_SECONDS
            )
            celery_app.send_task(
                "finreports.backfill_pnl",
                kwargs={"workspace_id": workspace_id, "chain": token},
                countdown=countdown,
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

    async def _guarded() -> dict[str, object]:
        """Record a death on the lane before letting it escape.

        The P&L lane has no ``autoretry_for`` — on this endpoint a retry ladder
        walks back into WB's fifteen-minute block and extends it — so an
        unrecorded exception is a walk that ends with nothing scheduled to
        notice. That is exactly how 2026-09-10 happened.
        """
        try:
            return await _run()
        except BaseException as error:
            await record_failure(
                workspace_id=uuid.UUID(workspace_id), lane=BackfillLane.PNL, error=error
            )
            raise

    return run_task(_guarded())


__all__ = [
    "PNL_EMPTY_STOP",
    "PNL_FLOOR_DAYS",
    "PNL_GAP_TOLERANCE_DAYS",
    "_format_cursor",
    "_parse_cursor",
    "advance_pnl",
    "backfill_pnl",
    "next_span",
]
