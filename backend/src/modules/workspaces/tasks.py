"""The watchdog that restarts a history backfill which stopped on its own.

Every lane is a chain: a tick does one bounded step, records it, and enqueues
the next. The chain's weakness is that it has exactly one thread of
continuation — if a tick dies without reaching its re-enqueue, nothing ever
starts it again. No retry catches it either, and deliberately so: on the
settlement endpoint a retry ladder walks straight back into WB's fifteen-minute
block and extends it.

That is not theoretical. On 2026-09-10 one workspace's P&L lane died on its FIRST tick —
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
One workspace ran two P&L chains for three hours on 2026-09-12, each at half of WB's
budget, and each in turn declared the lane complete.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, select

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
    BackfillLane.FUNNEL_SUMS: "monitoring.backfill_funnel_sums",
    BackfillLane.AD_CURRENCY: "monitoring.backfill_ad_currency",
}

#: How long to wait before restarting a lane, per lane. Absent means at once.
#:
#: Only the P&L lane has one, and it is not politeness — it is the cheapest
#: option available. A restart cannot know how much of WB's window the tick it
#: replaces had already spent, so it assumes none of it: three deploys in half
#: an hour each fired an immediate tick, and that is how one workspace drew
#: ``429 ... demands a 2762s wait`` on 2026-09-12 from a request 13 minutes
#: after the previous one.
#:
#: Ninety seconds, down from a quarter of an hour. The window it is standing
#: clear of is the Finance surface's minute rather than `reportDetailByPeriod`'s
#: fifteen, and a wait longer than the window it protects is pure delay on a
#: lane that has already been dead for :data:`STALE_AFTER`. Longer than one
#: refill rather than exactly one, because the refill starts whenever the dead
#: tick last spent a token and nothing records when that was.
#:
#: The other three lanes are paced by a bucket that refuses locally rather than
#: by a server-side penalty, so an early tick there is answered by their own
#: gate and costs nothing.
LANE_RESTART_DELAY: dict[BackfillLane, int] = {
    BackfillLane.PNL: 90,
}

#: How long a lane may go without moving before it is presumed dead.
#:
#: One figure for every lane, which it has not been since the P&L lane paced
#: itself in quarter-hours. That lane needed three hours of patience and the
#: monitoring lanes could not be given it — a dead catalogue would have meant an
#: afternoon of a new seller staring at an empty profile — so the patience was
#: per lane, and `SETTLEMENT_PACE_CEILING_SECONDS` was what the slow one's came
#: from.
#:
#: Forty-five minutes covers both families now, with the same margin for each:
#:
#: * the **P&L** lane runs a tick of at most 15 minutes (its soft time limit;
#:   the work inside it stops taking on pages at a derived 300 s) and then waits
#:   at most 15 (`finreports.tasks.backfill._PACE_CEILING_SECONDS`), so 45 is a
#:   lane that has missed the best part of a whole cycle and a half;
#: * the **monitoring** lanes tick every few seconds, except when they stand
#:   aside for the nightly harvest — a 20-minute yield, which 45 clears twice
#:   over.
#:
#: The invariant is the one thing to keep whatever the numbers become: patience
#: must exceed a tick's runtime plus its longest permitted wait. A lane
#: restarted for being exactly as slow as it was told to be is a lane whose
#: restart then asks early, which is what WB answers with a penalty block.
STALE_AFTER = timedelta(minutes=45)


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
        conditions.append(WorkspaceBackfill.updated_at < now - STALE_AFTER)
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
                else f"had not moved in {STALE_AFTER}",
                task_name,
                delay,
            )
        if stalled:
            logger.info("Backfill sweep restarted %d of %d stalled lanes.", restarted, len(stalled))
        return {"stalled": len(stalled), "restarted": restarted}

    return run_task(_run())
