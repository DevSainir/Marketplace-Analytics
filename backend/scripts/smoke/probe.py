"""Every page the probe opens, in the order its output lists them."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke.ab_tests import check_ab_tests
from scripts.smoke.finreports import check_pnl
from scripts.smoke.heatmap import check_heatmap
from scripts.smoke.monitoring import check_monitoring
from scripts.smoke.report import SmokeReport


async def smoke(session: AsyncSession, *, workspace_id: uuid.UUID) -> SmokeReport:
    """Open the main pages of one кабинет on the session given; collect what happened.

    Monitoring first: its busiest cards are what the entrypoint insists on
    having found, and the pages after it are opened whether or not it broke.
    """
    report = SmokeReport()
    await check_monitoring(session, report, workspace_id=workspace_id)
    await check_pnl(session, report, workspace_id=workspace_id)
    await check_heatmap(session, report, workspace_id=workspace_id)
    await check_ab_tests(session, report, workspace_id=workspace_id)
    return report


__all__ = ["smoke"]
