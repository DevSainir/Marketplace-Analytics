"""Is the settlement history sound — and if not, say who is short which days.

Detection, not harvesting, and the two are worth keeping apart: every counter
the harvest owns measures what a run DID — rows per source, sources that failed
— and a lost settlement day moves none of them. The walk succeeds, writes
exactly what it was asked for, and stops asking about a day WB had not served
yet. A gap is only ever visible in what the history does not contain, which is
why nothing noticed when 31.08 went missing from all five workspaces and it took
a person looking at WB's own site to find it.

The survey costs no WB request — it is one query per workspace — so it runs
across the whole fleet nightly even though the repair that follows is rationed
to one workspace. Knowing is cheap; walking is not.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.core.database import AsyncSessionLocal
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.metrics import SETTLEMENT_GAP_DAYS
from src.modules.finreports.constants import (
    RECONCILE_LOOKBACK_DAYS,
    SETTLEMENT_PUBLICATION_GRACE_DAYS,
)
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def survey_settlement_gaps(
    bundles: list[WorkspaceTokenBundle], *, today: date, announce: bool = True
) -> dict[uuid.UUID, list[date]]:
    """Find days no harvested report covers, and say so loudly enough to matter.

    The half the 31.08 incident was missing. Every counter the harvest had
    measured what a run DID — rows per source, failed sources — and a lost day
    moves none of them: the walk succeeded, wrote what it was asked for, and
    stopped asking about a day WB had not served yet. A gap is only visible in
    what the history does not contain.

    Reported twice, to the two audiences the observability split gives them:
    the fleet total to a metric, because `/metrics` has no tenancy check and so
    may not name a seller, and the days themselves to the log, which carries
    `workspace_id` on every line. Metrics answer "is anyone short a day"; logs
    answer "who, and which days".

    Args:
        bundles: Every workspace this run may look at.
        today: Today in Moscow time.
        announce: Whether to write the per-workspace ERROR lines. The metric is
            set either way — it is a gauge and a fresher one alerts sooner. The
            log is not: the hourly pass surveys too, and a stuck day logging an
            ERROR twenty-four times a day is how an alert stops being read. The
            daily pass announces; the hourly one repairs quietly.

    Returns:
        Uncovered days per workspace, omitting the workspaces that have none.
    """
    # Bounded to a little past the reconciliation's own reach. A hole older
    # than that cannot be repaired by the nightly pass, so raising it every
    # night would be an alarm nobody can act on — the surest way to teach
    # people to ignore this one.
    since = today - timedelta(days=RECONCILE_LOOKBACK_DAYS + 7)
    # And forward past the newest report we hold, which is where the hole that
    # matters most sits: a week WB published and nobody harvested is not between
    # two reports, it is after the last one. Bounded by the survey's own scan
    # end, the 07.09-13.09 week missing from three workspaces on 2026-09-14 was
    # reported as a sound history.
    through = today - timedelta(days=SETTLEMENT_PUBLICATION_GRACE_DAYS)
    gaps: dict[uuid.UUID, list[date]] = {}
    async with AsyncSessionLocal() as session:
        repo = FinancialReportRepository(session)
        for bundle in bundles:
            days = await repo.settlement_gap_days(
                workspace_id=bundle.workspace_id, since=since, through=through
            )
            if days:
                gaps[bundle.workspace_id] = days
    SETTLEMENT_GAP_DAYS.set(sum(len(days) for days in gaps.values()))
    for bundle in bundles:
        days = gaps.get(bundle.workspace_id, [])
        if days and announce:
            bind_workspace(bundle.workspace_id)
            logger.error(
                "finreports: %s has %d settlement day(s) no report covers: %s. WB serves "
                "back-dated reports late and the walk only looks forward, so these will "
                "not fix themselves outside the reconciliation window.",
                bundle.name,
                len(days),
                ", ".join(day.isoformat() for day in days),
            )
    return gaps


__all__ = ["survey_settlement_gaps"]
