"""The backfill record: what a new workspace's history walk has achieved.

A new organisation starts empty, and what fills it arrives on four different
clocks. The catalogue is one request. The funnel and advertising aggregates
refill a token every ~20 s, so a year of each is a couple of hours. The
settlement report serves **one request per fifteen minutes per token**, so a
large seller's P&L is sixteen hours of walking. This module owns the row that
says where each of those has got to.

It owns the *record*, not the walking. Nothing here calls WB or schedules
anything: the lanes live in ``monitoring`` and ``finreports``, and they report
in through :func:`record_progress`. The dependency runs one way — those modules
already import ``workspaces.contract`` for their token bundles — so putting the
record here is what keeps two modules from importing each other to share a
progress bar.

**The cursor and the progress bar are the same row** on purpose. "How far along
is this" and "where do we resume" are one fact with two readers, and keeping
them apart is how a resumed walk ends up reporting the progress of the run
before it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.modules.workspaces.models import BackfillLane, BackfillState, WorkspaceBackfill
from src.modules.workspaces.repos import BackfillRepository
from src.modules.workspaces.schemas import BackfillLaneStatus, BackfillStatusResponse

logger = get_logger(__name__)

#: What each lane is called on the seller's screen. Russian, because it is
#: rendered verbatim: the profile shows «Воронка», not "funnel".
LANE_LABELS: dict[BackfillLane, str] = {
    BackfillLane.CATALOGUE: "Каталог",
    BackfillLane.FUNNEL: "Воронка продаж",
    BackfillLane.ADVERTISING: "Реклама",
    BackfillLane.PNL: "Финансы (P&L)",
}

#: The order the profile renders them in — fastest first, so the seller sees
#: something finish while the slow one is still counting.
LANE_ORDER: tuple[BackfillLane, ...] = (
    BackfillLane.CATALOGUE,
    BackfillLane.FUNNEL,
    BackfillLane.ADVERTISING,
    BackfillLane.PNL,
)


@dataclass(frozen=True)
class LaneStep:
    """What one bounded step of a lane achieved, and whether it is finished.

    Lives here rather than in either lane because both ``monitoring`` and
    ``finreports`` return it, and a module importing the other's dataclass to
    describe its own progress is exactly the horizontal import the boundary
    rule forbids. ``workspaces`` already owns the record they report into.

    Attributes:
        done: Units walked so far — days for the funnel, 31-day windows for
            advertising, settlement days for P&L. The unit is the lane's own.
        total: Units in the whole walk. An ESTIMATE the lane may revise.
        cursor: Where the next step resumes; ``None`` when finished.
        finished: Whether the lane is complete. Authoritative, and not
            derivable from the counters: a walk that stops at WB's retention
            floor or at the seller's first trade ends with ``done < total`` and
            is nonetheless done.
        message: Russian, user-facing, rendered verbatim in the profile.
        rows: Rows written by this step, for the log.
    """

    done: int
    total: int
    cursor: str | None
    finished: bool
    message: str
    rows: int = 0


async def start_backfill(
    workspace_id: uuid.UUID, *, lanes: tuple[BackfillLane, ...] = LANE_ORDER
) -> None:
    """Seed a workspace's lanes as PENDING, replacing any previous run.

    Called once when a workspace's backfill is enqueued, so the profile has
    something to render immediately — a seller who has just finished signing up
    sees four lanes waiting rather than an empty panel that fills in minutes
    later, which is indistinguishable from nothing having started.

    **Never raises**, because its only caller is the token-save path, whose
    rule is that nothing attached to it may fail the seller's actual request
    (see :mod:`src.modules.workspaces.bootstrap`). Seeding is an optimisation,
    not a requirement: every lane's first tick upserts its own row anyway, so
    losing this costs the profile a minute of looking empty, never the run.

    Args:
        workspace_id: The workspace being backfilled.
        lanes: Which lanes this run will walk. A workspace with no advertising
            token still gets the lane, because "нет токена" is a state worth
            showing rather than a lane worth hiding.
    """
    try:
        async with AsyncSessionLocal() as session:
            repo = BackfillRepository(session)
            await repo.reset(workspace_id)
            for lane in lanes:
                await repo.upsert(
                    workspace_id=workspace_id,
                    lane=lane,
                    state=BackfillState.PENDING,
                    done_units=0,
                    total_units=0,
                    message="В очереди…",
                )
            await session.commit()
    except Exception:
        logger.exception(
            "Could not seed backfill lanes for workspace %s; the first tick will create them.",
            workspace_id,
        )
        return
    logger.info("Backfill lanes seeded for workspace %s.", workspace_id)


async def record_progress(
    *,
    workspace_id: uuid.UUID,
    lane: BackfillLane,
    state: BackfillState | None = None,
    done_units: int | None = None,
    total_units: int | None = None,
    cursor: str | None = None,
    message: str | None = None,
) -> None:
    """Record one lane's progress, in its own transaction.

    Owns its session deliberately. A tick task that wrote progress inside the
    transaction it ingests rows in would lose the progress whenever the ingest
    rolled back — and a lane that fails is exactly when its message matters
    most. Progress is a fact about the *attempt*, so it commits separately.

    Never raises: a broken progress write must not fail a tick that has
    genuinely harvested rows. The lane would look stalled, which the
    ``updated_at`` on the row already reveals.

    Args:
        workspace_id: The workspace being backfilled.
        lane: Which lane is reporting.
        state: New state, if it changed.
        done_units: Progress numerator, if it advanced.
        total_units: Progress denominator, if it was (re)estimated.
        cursor: The lane's private resume point, if it moved.
        message: User-facing Russian status line, if it changed.
    """
    try:
        async with AsyncSessionLocal() as session:
            await BackfillRepository(session).upsert(
                workspace_id=workspace_id,
                lane=lane,
                state=state,
                done_units=done_units,
                total_units=total_units,
                cursor=cursor,
                message=message,
            )
            await session.commit()
    except Exception:
        logger.exception(
            "Could not record backfill progress for workspace %s lane %s.", workspace_id, lane
        )


def _percent(row: WorkspaceBackfill) -> int:
    """A lane's completion, 0-100.

    A DONE lane reads 100 whatever the counters say, because ``total_units`` is
    an estimate and a walk that stopped early at WB's retention floor — the
    normal ending for a young account — would otherwise be frozen at 40% while
    saying «готово» beside it.
    """
    if row.state == BackfillState.DONE:
        return 100
    if row.total_units <= 0:
        return 0
    return max(0, min(100, round(row.done_units / row.total_units * 100)))


async def read_progress(session: AsyncSession, workspace_id: uuid.UUID) -> BackfillStatusResponse:
    """Return every lane of one workspace, in display order.

    Reads through the caller's own session so it inherits the tenancy context
    the route's ``PathWorkspaceId`` bound — this is a tenant-facing read, not a
    task-side one.

    Args:
        session: The request's session.
        workspace_id: The workspace, already validated against the caller's
            organisation by the route.

    Returns:
        The lanes, plus ``active``: whether anything is still moving, which is
        what tells the SPA to keep polling.
    """
    rows = {
        row.lane: row for row in await BackfillRepository(session).list_for_workspace(workspace_id)
    }
    lanes = [
        BackfillLaneStatus(
            lane=str(lane),
            label=LANE_LABELS[lane],
            state=row.state,
            done_units=row.done_units,
            total_units=row.total_units,
            percent=_percent(row),
            message=row.message,
            updated_at=row.updated_at,
        )
        for lane in LANE_ORDER
        if (row := rows.get(lane)) is not None
    ]
    active = any(lane.state in (BackfillState.PENDING, BackfillState.RUNNING) for lane in lanes)
    return BackfillStatusResponse(active=active, lanes=lanes)


async def read_cursor(*, workspace_id: uuid.UUID, lane: BackfillLane) -> str | None:
    """Return one lane's resume point, or ``None`` if it has never ticked."""
    async with AsyncSessionLocal() as session:
        row = await BackfillRepository(session).get(workspace_id=workspace_id, lane=lane)
        return None if row is None else row.cursor


__all__ = [
    "LANE_LABELS",
    "LANE_ORDER",
    "BackfillLane",
    "BackfillState",
    "LaneStep",
    "read_cursor",
    "read_progress",
    "record_progress",
    "start_backfill",
]
