"""A backfill lane must look alive whenever it actually ticked.

Everything that decides whether a lane has died reads one column: the watchdog
restarts what has not moved, and on the settlement endpoint that restart then
waits a full WB window before asking — so a lane wrongly judged dead pays a
quarter of an hour for it.

The trap is that the commonest HEALTHY tick changes nothing. A lane waiting out
WB's window records the same message it recorded last time, and an ORM that
stamps `updated_at` via `onupdate` emits no UPDATE at all when no value differs.
Observed on one workspace 2026-09-15: a lane that had ticked twenty seconds earlier
reported `updated_at` 2h51m old.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import Organization
from src.modules.workspaces.models import BackfillLane, BackfillState, Workspace
from src.modules.workspaces.repos import BackfillRepository


@pytest.fixture
async def workspace(db_session: AsyncSession, organization: Organization) -> Workspace:
    ws = Workspace(name="Backfill liveness", organization_id=organization.id, is_primary=False)
    db_session.add(ws)
    await db_session.flush()
    return ws


async def test_a_tick_that_changes_nothing_still_counts_as_a_tick(
    db_session: AsyncSession, workspace: Workspace
) -> None:
    """The exact shape of a lane waiting on WB, twice in a row.

    Same message, same counters, same cursor — and it must still read as fresh,
    because the lane did run. Judging it dead costs a restart the endpoint
    charges a whole window for.
    """
    repo = BackfillRepository(db_session)
    waiting = "Waiting for a Wildberries slot (1 request per 15 minutes)…"

    first = await repo.upsert(
        workspace_id=workspace.id,
        lane=BackfillLane.PNL,
        state=BackfillState.RUNNING,
        message=waiting,
    )
    was = first.updated_at

    second = await repo.upsert(
        workspace_id=workspace.id,
        lane=BackfillLane.PNL,
        state=BackfillState.RUNNING,
        message=waiting,
    )

    assert second.updated_at > was, (
        "a lane that ticked reads as stale, so the watchdog will restart it for being healthy"
    )


async def test_progress_still_moves_the_stamp(
    db_session: AsyncSession, workspace: Workspace
) -> None:
    """The ordinary case must not have been broken by fixing the quiet one."""
    repo = BackfillRepository(db_session)

    first = await repo.upsert(
        workspace_id=workspace.id, lane=BackfillLane.PNL, done_units=1, message="Collecting…"
    )
    was = first.updated_at

    second = await repo.upsert(workspace_id=workspace.id, lane=BackfillLane.PNL, done_units=2)

    assert second.updated_at > was
    assert second.done_units == 2
