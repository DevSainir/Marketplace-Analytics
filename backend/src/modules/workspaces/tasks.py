"""The watchdog that restarts a history backfill which stopped on its own.

Every lane is a chain: a tick does one bounded step, records it, and enqueues
the next. The chain's weakness is that it has exactly one thread of
continuation — if a tick dies without reaching its re-enqueue, nothing ever
starts it again. No retry catches it either, and deliberately so: on the
settlement endpoint a retry ladder walks straight back into WB's fifteen-minute
block and extends it.

That is not theoretical. On 2026-09-10 NEVA's P&L lane died on its FIRST tick —
the lane asked the rate gate for a token, the gate answered "waiting 956 s",
and Celery's 300 s soft limit killed the task. `SoftTimeLimitExceeded` is not
an `IntegrationError`, so the lane's own "window still shut" branch never ran,
no progress row was written, and a thirteen-hour walk was over in five minutes
with nothing in the logs anyone was watching. Eleven hours passed before a
person happened to look.

So the chain gets a second thread of continuation that nothing in a tick can
break: a sweep, on the beat schedule, that looks for lanes which claim to be
running and have not moved, and enqueues them again. It is idempotent by
construction — every lane resumes from the cursor in its own row, so starting
one that is actually alive costs a duplicate step, not a duplicate walk.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.core.celery_app import celery_app
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.observability.metrics import (
    BACKFILL_LANE_RESTARTS,
    BACKFILL_LANES_STALLED,
)
from src.core.tasks import run_task
from src.modules.workspaces.models import BackfillLane, BackfillState, WorkspaceBackfill

logger = get_logger(__name__)

#: Which task restarts which lane. Strings rather than imports for the reason
#: the whole module keeps them that way — ``workspaces`` must not import
#: ``monitoring`` or ``finreports`` — and
#: ``tests/unit/workspaces/test_token_bootstrap.py`` asserts every one of them
#: resolves to a registered task, so a rename fails the build rather than
#: quietly disabling the watchdog.
LANE_TASKS: dict[BackfillLane, str] = {
    BackfillLane.CATALOGUE: "monitoring.backfill_catalogue",
    BackfillLane.FUNNEL: "monitoring.backfill_funnel",
    BackfillLane.ADVERTISING: "monitoring.backfill_advertising",
    BackfillLane.PNL: "finreports.backfill_pnl",
}

#: How long a lane may go without moving before it is presumed dead.
#:
#: Set from the slowest lane's own cadence, not from impatience: the P&L tick
#: re-enqueues itself every ~15.5 minutes, and a tick that finds WB's window
#: shut legitimately records nothing new but its message. Forty-five minutes is
#: three of those — long enough that a healthy slow lane is never restarted,
#: short enough that a dead one loses at most two pages.
STALE_AFTER = timedelta(minutes=45)


async def _stalled(now: datetime) -> list[tuple[uuid.UUID, str]]:
    """Lanes that claim to be working and have not moved since ``STALE_AFTER``.

    PENDING counts as stalled as well as RUNNING: a lane seeded at signup whose
    first tick never arrived — a broker hiccup, a worker recreated in the wrong
    second — looks exactly like this and has the same fix.
    """
    cutoff = now - STALE_AFTER
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(WorkspaceBackfill.workspace_id, WorkspaceBackfill.lane).where(
                WorkspaceBackfill.state.in_([BackfillState.PENDING, BackfillState.RUNNING]),
                WorkspaceBackfill.updated_at < cutoff,
            )
        )
        return [(workspace_id, lane) for workspace_id, lane in rows.all()]


@celery_app.task(  # type: ignore[untyped-decorator]
    name="workspaces.sweep_stalled_backfills",
    soft_time_limit=120,
    time_limit=180,
)
def sweep_stalled_backfills() -> dict[str, int]:
    """Re-enqueue every backfill lane that has stopped moving.

    Cheap and safe to run often: one indexed read, and an enqueue only for a
    lane that has genuinely gone quiet. Restarting a lane that turns out to be
    alive is harmless — it resumes from the same cursor, so the worst case is
    one page fetched twice, and the ingestion is an upsert.

    Returns:
        ``{"stalled": n, "restarted": n}`` — the two differ only when a lane's
        task name is unknown, which is a bug in :data:`LANE_TASKS` rather than
        a state a workspace can reach.
    """

    async def _run() -> dict[str, int]:
        stalled = await _stalled(datetime.now(UTC))
        # Published BEFORE any restart is attempted, so the gauge describes what
        # the sweep FOUND rather than what it left behind. A gauge written after
        # a successful restart would read zero on every scrape and the alert on
        # it would never fire — the monitoring equivalent of the bug this whole
        # module exists for.
        BACKFILL_LANES_STALLED.set(len(stalled))
        restarted = 0
        for workspace_id, lane in stalled:
            task_name = LANE_TASKS.get(BackfillLane(lane))
            if task_name is None:
                logger.error("No restart task registered for backfill lane %r.", lane)
                continue
            celery_app.send_task(task_name, kwargs={"workspace_id": str(workspace_id)})
            BACKFILL_LANE_RESTARTS.labels(lane=lane).inc()
            restarted += 1
            logger.warning(
                "Backfill lane %s for workspace %s had not moved in %s; restarted it via %s.",
                lane,
                workspace_id,
                STALE_AFTER,
                task_name,
            )
        if stalled:
            logger.info("Backfill sweep restarted %d of %d stalled lanes.", restarted, len(stalled))
        return {"stalled": len(stalled), "restarted": restarted}

    return run_task(_run())
