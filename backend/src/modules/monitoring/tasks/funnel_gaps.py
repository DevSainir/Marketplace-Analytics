"""Is the funnel history whole — and if not, fill what WB still serves.

The funnel's twin of ``finreports/tasks/gaps.py``, for the same reason: every
counter the harvest and the backfill own measures what a run DID, and a day
nobody asked about moves none of them. On 2026-09-29 the backfill lane left
07.09 to the nightly cohort pass, the pass of 30.09 no longer read it, and the
day's order sums were missing for three days with every run green.

So at the end of each nightly cohort pass this looks at the days that pass no
longer reads — older than its window, younger than WB's 365-day reach — for an
article that sold and still lacks WB's money or its cohort, re-reads a couple
of them from WB's aggregate, and reports what is left: the fleet total to a
metric (``/metrics`` may not name a seller), the days themselves to the log,
which carries ``workspace_id``.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.core.database import AsyncSessionLocal
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.modules.monitoring.repos import FunnelRepository, ProductCardRepository
from src.modules.monitoring.services.backfill import FUNNEL_DAYS, advance_funnel
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Gap days re-read per кабинет per night, newest first. Each is one paced
#: aggregate call (~20 s); two keep the night inside its budget
#: (``tests/unit/core/test_nightly_work_ends_before_the_workday.py``) and still
#: clear a one-off hole the next morning.
MAX_REPAIRS_PER_NIGHT = 2


async def heal_funnel_gaps(
    bundle: WorkspaceTokenBundle, *, today: date, cohort_days: int
) -> list[date]:
    """Re-read this кабинет's newest incomplete funnel days; return those still incomplete.

    Args:
        bundle: The кабинет's decrypted tokens.
        today: Today in Moscow time.
        cohort_days: How far back the nightly cohort pass reads — its days are
            its own, and are not holes yet.
    """
    yesterday = today - timedelta(days=1)
    since = yesterday - timedelta(days=FUNNEL_DAYS - 2)
    through = yesterday - timedelta(days=cohort_days)
    async with AsyncSessionLocal() as session:
        nm_ids = await ProductCardRepository(session).list_workspace_nm_ids(bundle.workspace_id)
        gaps = await FunnelRepository(session).incomplete_days(
            nm_ids=nm_ids, since=since, through=through
        )
    if not gaps or not bundle.analytics:
        return gaps
    for day in reversed(gaps[-MAX_REPAIRS_PER_NIGHT:]):
        await advance_funnel(bundle, nm_ids=nm_ids, cursor=day.isoformat(), days_per_tick=1)
    async with AsyncSessionLocal() as session:
        return await FunnelRepository(session).incomplete_days(
            nm_ids=nm_ids, since=since, through=through
        )


def announce_funnel_gaps(bundle: WorkspaceTokenBundle, days: list[date]) -> None:
    """Name the кабинет and the days in the log — the metric may not."""
    if not days:
        return
    bind_workspace(bundle.workspace_id)
    logger.error(
        "monitoring: %s has %d funnel day(s) an article sold on with no WB sum or cohort: %s. "
        "The nightly pass re-reads %d a night; a day that stays has to be fetched by hand.",
        bundle.name,
        len(days),
        ", ".join(day.isoformat() for day in days),
        MAX_REPAIRS_PER_NIGHT,
    )


__all__ = ["MAX_REPAIRS_PER_NIGHT", "announce_funnel_gaps", "heal_funnel_gaps"]
