"""Backfill phase: the funnel-aggregate history walk.

WB's daily funnel endpoint serves only the last 7 days, so everything older has
to be reconstructed one day at a time from the period aggregate. That pacing —
one rate-limited call per day walked — is why this phase dominates a backfill's
runtime, and why it skips days it has already healed.

Shared with ``seed_workspace.py``, which runs the same walk over a shorter
window; the two differ only in how far back they reach.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.backfill.common import PhaseTotals, _build_service, _is_http_400
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAnalyticsClient
from src.modules.monitoring.models import SalesFunnelDaily
from src.modules.monitoring.tasks import COHORT_REFRESH_DAYS
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Phase 2 — daily funnel + matured cohorts (analytics aggregate, 1 call/day)
# --------------------------------------------------------------------------- #
async def _funnel_coverage(
    session: AsyncSession, *, nm_ids: list[int], since: date
) -> dict[date, dict[int, bool]]:
    """Existing funnel rows per day: ``{day: {nm_id: cancel_count is set}}``."""
    stmt = select(
        SalesFunnelDaily.stat_date, SalesFunnelDaily.nm_id, SalesFunnelDaily.cancel_count
    ).where(SalesFunnelDaily.nm_id.in_(nm_ids), SalesFunnelDaily.stat_date >= since)
    result = await session.execute(stmt)
    coverage: dict[date, dict[int, bool]] = {}
    for stat_date, nm_id, cancel_count in result.all():
        coverage.setdefault(stat_date, {})[nm_id] = cancel_count is not None
    return coverage


async def _backfill_funnel(
    tokens: WorkspaceTokenBundle,
    *,
    nm_ids: list[int],
    days: int,
    pause: float,
    empty_stop: int,
    totals: PhaseTotals,
) -> None:
    """Reconstruct the daily funnel series day-by-day from the aggregate.

    Walks from yesterday backwards. Per day, ONE aggregate call answers for
    the whole catalogue; its rows are split into

    * UPDATEs — ``(day, nm)`` already stored: refresh the matured
      ``buyout_count``/``cancel_count`` (heals days that froze at ≤7-day
      maturity before the cohort pipeline existed);
    * INSERTs — ``(day, nm)`` absent: write the full funnel row (the only way
      to obtain days older than the 7-day daily-history window).

    Skip rules make re-runs cheap: a day inside the nightly cohort window is
    the scheduled task's job; a day whose rows all carry a ``cancel_count`` was
    already healed by a previous run. Walking stops early at the WB retention
    floor (HTTP 400) or after ``empty_stop`` consecutive zero-activity days
    (predating the seller's first trade).
    """
    if not tokens.analytics:
        logger.warning("Workspace '%s' has no analytics token; funnel skipped.", tokens.name)
        return

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    wanted = set(nm_ids)

    async with AsyncSessionLocal() as session:
        coverage = await _funnel_coverage(session, nm_ids=nm_ids, since=start)

    empty_streak = 0
    async with WBAnalyticsClient(settings, token=tokens.analytics) as client:
        for offset in range(days):
            day = end - timedelta(days=offset)
            existing = coverage.get(day, {})
            if existing and offset < COHORT_REFRESH_DAYS:
                continue  # the nightly cohort task owns the maturing window
            if existing and all(existing.values()):
                empty_streak = 0
                continue  # healed by a previous run — resume point
            try:
                rows = await client.fetch_funnel_cohort_day(day=day)
            except IntegrationError as exc:
                if _is_http_400(exc):
                    logger.info("WB stops serving the aggregate at %s; funnel done.", day)
                    break
                logger.warning("Funnel day %s failed (%s); continuing.", day, exc)
                continue

            async with AsyncSessionLocal() as session:
                service = _build_service(session)
                updated = inserted = 0
                if existing:
                    updated = await service.ingest_funnel_cohorts(day, rows, nm_ids=set(existing))
                inserted = await service.ingest_funnel_backfill(
                    day, rows, nm_ids=wanted - set(existing)
                )
                await session.commit()
            totals.add("funnel_rows_inserted", inserted)
            totals.add("funnel_cohorts_updated", updated)

            if inserted == 0 and not existing:
                empty_streak += 1
                if empty_streak >= empty_stop:
                    logger.info(
                        "%d consecutive zero-activity days before %s — assuming this "
                        "predates the first trade; funnel done.",
                        empty_streak,
                        day,
                    )
                    break
            else:
                empty_streak = 0
            await asyncio.sleep(pause)  # ~1 req/20s surface
