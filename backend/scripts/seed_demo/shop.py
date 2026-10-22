"""The whole shop, written into one workspace — shared by the demo and the e2e tier."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo.ab_tests import seed_ab_tests
from scripts.seed_demo.advertising import seed_advertising
from scripts.seed_demo.extras import seed_heatmap
from scripts.seed_demo.monitoring import seed_monitoring
from scripts.seed_demo.settlement import seed_settlement


async def populate_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, today: date
) -> dict[str, int]:
    """Write the whole shop into one workspace. The caller owns the transaction.

    The shop's WB ids are fixed, so this runs once per database: it is for a
    database that holds no shop yet — the demo after its wipe, or a fresh
    end-to-end stack.

    Returns:
        Rows written per area.
    """
    return {
        "monitoring": await seed_monitoring(session, workspace_id, today),
        "advertising": await seed_advertising(session, today),
        "settlement": await seed_settlement(session, workspace_id, today),
        "heatmap": await seed_heatmap(session, workspace_id),
        "ab_tests": await seed_ab_tests(session, workspace_id, today),
    }
