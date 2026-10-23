"""Backfill phase: WB's advertising write-off ledger (who funded the ads).

``GET /adv/v1/upd`` is the only WB surface that says whether an advertising
charge came out of the seller's own money (balance) or out of WB's bonus pool
(cashback). The nightly harvest keeps a rolling seven days current; everything
older has to be walked once, which is what this phase does.

It is cheap by the standards of the other phases: the feed is account-wide with
no campaign filter, so the whole history costs one request per month — about two
dozen calls for two years, against the thousands fullstats needs.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from scripts.backfill.common import PhaseTotals, _build_service
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: One request per calendar month of history. WB rejects a wider interval, and
#: the client walks it in 30-day steps anyway — this is the INGEST window, which
#: must match what was fetched because the ingest sweeps before it writes.
_WINDOW_DAYS = 30


async def _backfill_write_offs(
    tokens: WorkspaceTokenBundle, *, days: int, pause: float, totals: PhaseTotals
) -> None:
    """Walk the write-off ledger backwards, one bounded window at a time.

    Each window is fetched and ingested on its own so an interrupted run leaves
    every completed window persisted — the ingest sweeps and rewrites exactly
    the window it was given, so re-running is idempotent and a partial history
    is simply a shorter one.

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: How far back to walk from yesterday.
        pause: Seconds to wait between windows (the surface's own limiter).
        totals: Shared counters for the run's final report.
    """
    if not tokens.advertising:
        logger.warning("Workspace '%s' has no promotion token; write-offs skipped.", tokens.name)
        return

    end = moscow_today() - timedelta(days=1)
    floor = end - timedelta(days=days - 1)
    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        window_end = end
        while window_end >= floor:
            window_start = max(window_end - timedelta(days=_WINDOW_DAYS - 1), floor)
            try:
                rows = await client.fetch_write_offs(date_from=window_start, date_to=window_end)
            except IntegrationError as exc:
                # A refused window costs that window, not the walk: the older
                # ones behind it are still worth having, and the ledger is
                # re-fetchable at any time.
                logger.warning(
                    "Write-off window %s..%s failed for '%s': %s",
                    window_start,
                    window_end,
                    tokens.name,
                    exc,
                )
                window_end = window_start - timedelta(days=1)
                continue

            async with AsyncSessionLocal() as session:
                service = _build_service(session)
                written = await service.ingest_write_offs(rows, window=(window_start, window_end))
                await session.commit()
            totals.add("ad_write_offs", written)
            logger.info(
                "Write-offs %s..%s: %d WB rows -> %d buckets.",
                window_start,
                window_end,
                len(rows),
                written,
            )
            window_end = window_start - timedelta(days=1)
            if window_end >= floor and pause:
                await asyncio.sleep(pause)
