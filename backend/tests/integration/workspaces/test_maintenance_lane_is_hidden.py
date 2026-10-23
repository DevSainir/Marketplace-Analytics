"""A maintenance re-walk must not reappear on a seller's profile.

``funnel_sums`` re-walks the funnel of workspaces whose history loaded long ago,
to fill the sums first stored on 2026-09-29. It reports into the same table the
profile reads "Loading history" from, and a seller seeing that strip come back
months after signup would reasonably think their data had been lost.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import Organization
from src.modules.workspaces.backfill import read_progress
from src.modules.workspaces.models import BackfillLane, BackfillState, Workspace
from src.modules.workspaces.repos import BackfillRepository


@pytest.fixture
async def workspace(db_session: AsyncSession, organization: Organization) -> Workspace:
    ws = Workspace(name="Maintenance lane", organization_id=organization.id, is_primary=False)
    db_session.add(ws)
    await db_session.flush()
    return ws


async def test_a_running_maintenance_lane_shows_nothing_and_keeps_nothing_polling(
    db_session: AsyncSession, workspace: Workspace
) -> None:
    """No lane on the strip, and ``active`` false — so the strip stays hidden."""
    await BackfillRepository(db_session).upsert(
        workspace_id=workspace.id,
        lane=BackfillLane.FUNNEL_SUMS,
        state=BackfillState.RUNNING,
        message="Collecting the funnel: 40 of 365 days.",
    )

    progress = await read_progress(db_session, workspace.id)

    assert progress.lanes == []
    assert progress.active is False
