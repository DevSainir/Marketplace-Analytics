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
running and have not moved, and enqueues them again.

It is free to be wrong about whether a lane is dead, and that freedom is
:mod:`src.modules.workspaces.chain` rather than a property of the sweep. A
restart claims the lane's chain token, so a tick the sweep was wrong about
retires itself when it next wakes instead of walking alongside the replacement.
Without that the sweep bought its safety net at the price of forking the lane —
NEVA ran two P&L chains for three hours on 2026-09-12, each at half of WB's
budget, and each in turn declared the lane complete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, or_, select

from src.core.celery_app import celery_app
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.observability.metrics import (
    BACKFILL_LANE_RESTARTS,
    BACKFILL_LANES_STALLED,
)
from src.core.tasks import run_task
from src.integrations.wildberries.rate_limit.surfaces import SETTLEMENT_PACE_CEILING_SECONDS
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
    BackfillLane.ORDERS: "monitoring.backfill_orders",
    BackfillLane.PNL: "finreports.backfill_pnl",
}

#: How long to wait before restarting a lane, per lane. Absent means at once.
#:
#: Only the P&L lane has one, and it is not politeness — it is the cheapest
#: option available. WB serves ``reportDetailByPeriod`` once per ~15 minutes per
#: token and answers an early ask with a PENALTY block: measured on NEVA
#: 2026-09-12, a request 13 minutes after the previous one drew
#: ``429 ... demands a 2762s wait``, turning a quarter-hour window into
#: three quarters of an hour of nothing.
#:
#: A restart is exactly where that happens. The tick it replaces was killed
#: mid-step, so nothing knows whether it had just spent the window or was still
#: waiting for it — and three deploys in half an hour each fired an immediate
#: tick, which is how NEVA earned the block above. Waiting one full window costs
#: a lane that was genuinely dead ~15 minutes on top of the 45 it had already
#: lost; guessing wrong costs 46 and leaves the walk no further forward.
#:
#: The other three lanes are paced by a bucket that refuses locally rather than
#: by a server-side penalty, so an early tick there is answered by their own
#: gate and costs nothing.
LANE_RESTART_DELAY: dict[BackfillLane, int] = {
    BackfillLane.PNL: 15 * 60 + 30,
}

#: How long a lane may go without moving before it is presumed dead.
#:
#: Set from the slowest lane's own cadence, not from impatience: the P&L tick
#: re-enqueues itself every ~15.5 minutes, and a tick that finds WB's window
#: shut legitimately records nothing new but its message. Forty-five minutes is
#: three of those — long enough that a healthy slow lane is never restarted,
#: short enough that a dead one loses at most two pages.
STALE_AFTER = timedelta(minutes=45)

#: Lanes whose own cadence is slower than :data:`STALE_AFTER`, and how long they
#: may therefore go quiet.
#:
#: The P&L lane paces itself against WB rather than against a constant, widening
#: its interval whenever a page is refused. A watchdog fixed at 45 minutes
#: therefore capped that interval at 40 — and a lane pinned against a cap it
#: wants to cross keeps asking too early. Measured on NEVA over six hours:
#: four pages served against six refusals, roughly 40% of an endpoint's whole
#: daily budget spent on requests WB was always going to reject.
#:
#: Twice the pace ceiling: the lane records progress on every tick, including a
#: refused one, so two intervals of silence is a lane that has genuinely stopped
#: rather than one waiting out its longest permitted wait.
LANE_STALE_AFTER: dict[BackfillLane, timedelta] = {
    BackfillLane.PNL: timedelta(seconds=SETTLEMENT_PACE_CEILING_SECONDS * 2),
}


def _patience(lane: BackfillLane) -> timedelta:
    """How long this lane may go without moving before it is presumed dead."""
    return LANE_STALE_AFTER.get(lane, STALE_AFTER)


async def _stalled(now: datetime, *, orphaned: bool = False) -> list[tuple[uuid.UUID, str]]:
    """Lanes that claim to be working and are not.

    PENDING counts as well as RUNNING: a lane seeded at signup whose first tick
    never arrived — a broker hiccup, a worker recreated in the wrong second —
    looks exactly like this and has the same fix.

    Args:
        now: The moment to measure staleness against.
        orphaned: Skip the age test entirely. Only ever true when a worker has
            just started, and then it is not a guess but a fact: a fresh worker
            is running nothing, so every lane still claiming to be RUNNING was
            killed mid-tick by whatever restarted it. Waiting out
            :data:`STALE_AFTER` to rediscover that would leave a seller's
            history stopped for three quarters of an hour after every deploy.
    """
    conditions: list[ColumnElement[bool]] = [
        WorkspaceBackfill.state.in_([BackfillState.PENDING, BackfillState.RUNNING])
    ]
    if not orphaned:
        # Per lane, because they do not run at the same speed. One flat
        # threshold is what forced the slowest lane's pacing to fit the fastest
        # lane's idea of dead.
        conditions.append(
            or_(
                *(
                    and_(
                        WorkspaceBackfill.lane == lane,
                        WorkspaceBackfill.updated_at < now - _patience(lane),
                    )
                    for lane in BackfillLane
                )
            )
        )
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(WorkspaceBackfill.workspace_id, WorkspaceBackfill.lane).where(*conditions)
        )
        return [(workspace_id, lane) for workspace_id, lane in rows.all()]


@celery_app.task(  # type: ignore[untyped-decorator]
    name="workspaces.sweep_stalled_backfills",
    soft_time_limit=120,
    time_limit=180,
)
def sweep_stalled_backfills(orphaned: bool = False) -> dict[str, int]:
    """Re-enqueue every backfill lane that has stopped moving.

    Cheap and safe to run often: one indexed read, and an enqueue only for a
    lane that has gone quiet. Restarting a lane that turns out to be alive is
    harmless: the restart is enqueued WITHOUT a chain token, which claims the
    lane, so the surviving tick stops at its next wake and only one chain walks
    on — from the cursor in the row, so the worst case is one page fetched
    twice into an upsert.

    The restart is delayed by :data:`LANE_RESTART_DELAY` where the lane's
    endpoint punishes an early ask. Being wrong about a dead lane is cheap;
    being early on the settlement endpoint is not.

    Args:
        orphaned: Restart every lane that claims to be running, without waiting
            for it to look stale. Sent by the worker-start hook, where a lane in
            RUNNING is by definition one nothing is running.

    Returns:
        ``{"stalled": n, "restarted": n}`` — the two differ only when a lane's
        task name is unknown, which is a bug in :data:`LANE_TASKS` rather than
        a state a workspace can reach.
    """

    async def _run() -> dict[str, int]:
        stalled = await _stalled(datetime.now(UTC), orphaned=orphaned)
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
            delay = LANE_RESTART_DELAY.get(BackfillLane(lane), 0)
            celery_app.send_task(
                task_name, kwargs={"workspace_id": str(workspace_id)}, countdown=delay
            )
            BACKFILL_LANE_RESTARTS.labels(lane=lane).inc()
            restarted += 1
            logger.warning(
                "Backfill lane %s for workspace %s %s; restarting it via %s in %ds.",
                lane,
                workspace_id,
                "was orphaned by a worker restart"
                if orphaned
                else f"had not moved in {_patience(BackfillLane(lane))}",
                task_name,
                delay,
            )
        if stalled:
            logger.info("Backfill sweep restarted %d of %d stalled lanes.", restarted, len(stalled))
        return {"stalled": len(stalled), "restarted": restarted}

    return run_task(_run())
