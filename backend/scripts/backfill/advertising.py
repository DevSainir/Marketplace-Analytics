"""Backfill phase: campaign fullstats and their search-zone slices.

The fullstats endpoint caps one request at 31 days, so a year of history is a
sequence of window slices per campaign — and a campaign is only worth a slice
from the day it first delivered, which is what the per-campaign minimum dates
are for.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.backfill.common import (
    _BACKFILL_STATUSES,
    _FULLSTATS_WINDOW_DAYS,
    PhaseTotals,
    _build_service,
)
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient
from src.integrations.wildberries.schemas import WBAdvertV2, WBCampaign
from src.modules.monitoring.models import AdvertisingSearchStatDaily, AdvertisingStatDaily
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Phase 3 — advertising fullstats + search-zone slices, in 31-day windows
# --------------------------------------------------------------------------- #
def _window_slices(*, end: date, days: int) -> list[tuple[date, date]]:
    """Inclusive 31-day-max windows from ``end`` walking backwards."""
    slices: list[tuple[date, date]] = []
    hi = end
    floor = end - timedelta(days=days - 1)
    while hi >= floor:
        lo = max(hi - timedelta(days=_FULLSTATS_WINDOW_DAYS - 1), floor)
        slices.append((lo, hi))
        hi = lo - timedelta(days=1)
    return slices


def _search_pairs_for(
    adverts: list[WBAdvertV2], campaign_ids: set[int], nm_ids: set[int]
) -> list[tuple[int, int]]:
    """(campaign, SKU) pairs whose search-zone slice is worth requesting."""
    pairs: set[tuple[int, int]] = set()
    for advert in adverts:
        if advert.campaign_id not in campaign_ids or not advert.settings.placements.search:
            continue
        for setting in advert.nm_settings:
            if setting.nm_id in nm_ids:
                pairs.add((advert.campaign_id, setting.nm_id))
    return sorted(pairs)


async def _min_dates_by_campaign(
    session: AsyncSession, model: type[AdvertisingStatDaily] | type[AdvertisingSearchStatDaily]
) -> dict[int, date]:
    """Earliest stored ``stat_date`` per campaign for a fact table."""
    stmt = select(model.campaign_id, func.min(model.stat_date)).group_by(model.campaign_id)
    result = await session.execute(stmt)
    return dict(result.tuples().all())


async def _backfill_advertising(
    tokens: WorkspaceTokenBundle,
    *,
    nm_ids: list[int],
    days: int,
    pause: float,
    totals: PhaseTotals,
) -> None:
    """Backfill fullstats and normquery history for ALL delivering campaigns.

    Unlike the nightly harvest (active/paused only — nothing else has *recent*
    data), history belongs mostly to COMPLETED campaigns, so status 7 joins the
    set. Coverage is judged per campaign by its earliest stored row: a window
    already inside coverage is skipped, so re-runs only touch real gaps.
    Campaigns with no stored rows are (re-)requested every run — WB answers
    empty cheaply and the ingestion sweep keeps it idempotent.
    """
    if not tokens.advertising:
        logger.warning("Workspace '%s' has no advertising token; ads skipped.", tokens.name)
        return

    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        campaigns: list[WBCampaign] = await client.list_campaigns()
        adverts: list[WBAdvertV2] | None
        try:
            adverts = await client.list_adverts()
        except IntegrationError as exc:
            logger.warning("adverts-v2 failed (%s); campaign settings not refreshed.", exc)
            adverts = None

        async with AsyncSessionLocal() as session:
            service = _build_service(session)
            await service.ingest_campaigns(campaigns, adverts)
            await session.commit()

        target_ids = {c.campaign_id for c in campaigns if c.status in _BACKFILL_STATUSES}
        if not target_ids:
            logger.info("No campaigns with historical potential; advertising done.")
            return

        end = moscow_today() - timedelta(days=1)
        slices = _window_slices(end=end, days=days)

        async with AsyncSessionLocal() as session:
            full_cov = await _min_dates_by_campaign(session, AdvertisingStatDaily)
            search_cov = await _min_dates_by_campaign(session, AdvertisingSearchStatDaily)

        pairs = _search_pairs_for(adverts or [], target_ids, set(nm_ids))

        for lo, hi in slices:
            # fullstats: campaigns whose stored history does not reach lo yet.
            needed = sorted(cid for cid in target_ids if cid not in full_cov or full_cov[cid] > lo)
            if needed:
                try:
                    stats = await client.fetch_full_stats(
                        campaign_ids=needed, date_from=lo, date_to=hi
                    )
                except IntegrationError as exc:
                    # NOT a stop signal: WB also answers 400 when every
                    # requested campaign had zero impressions in the window
                    # (per the WB dev forum) — deeper windows may still hold
                    # data for other campaigns.
                    logger.warning("fullstats %s..%s failed (%s); continuing.", lo, hi, exc)
                    stats = []
                if stats:
                    async with AsyncSessionLocal() as session:
                        service = _build_service(session)
                        count = await service.ingest_advertising(stats, window=(lo, hi))
                        await session.commit()
                    totals.add("advertising_rows", count)
                await asyncio.sleep(pause)  # ~1 req/min surface

            # normquery: same window, search-placement campaigns not yet covered.
            slice_pairs = [
                (cid, nm) for cid, nm in pairs if cid not in search_cov or search_cov[cid] > lo
            ]
            if slice_pairs:
                try:
                    items = await client.fetch_search_zone_stats(
                        pairs=slice_pairs, date_from=lo, date_to=hi
                    )
                except IntegrationError as exc:
                    logger.warning("normquery %s..%s failed (%s); continuing.", lo, hi, exc)
                    items = None
                if items is not None:
                    async with AsyncSessionLocal() as session:
                        service = _build_service(session)
                        count = await service.ingest_search_stats(
                            items,
                            window=(lo, hi),
                            requested_campaign_ids=sorted({cid for cid, _ in slice_pairs}),
                        )
                        await session.commit()
                    totals.add("search_zone_rows", count)
