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
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.modules.finreports.tasks.backfill.span import (
    PNL_EMPTY_STOP,
    PNL_FLOOR_DAYS,
    PNL_GAP_TOLERANCE_DAYS,
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

#: Seconds before the next page. WB's own budget on this endpoint — asking
#: sooner restarts its window and makes the lane slower, not faster.
_NEXT_PAGE_SECONDS = 15 * 60 + 30

#: A tick is one request plus one ingest; the limit is a hung-call backstop.
_TICK_SOFT_LIMIT_SECONDS = 5 * 60


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
            celery_app.send_task(
                "finreports.backfill_pnl",
                kwargs={"workspace_id": workspace_id, "chain": token},
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
