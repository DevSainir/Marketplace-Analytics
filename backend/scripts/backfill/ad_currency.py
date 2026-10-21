"""Backfill phase: the currency of advertising spend harvested without one.

Until 2026-09-29 the harvest dropped the ``currency`` fullstats states on each
campaign, so every older ``advertising_stat_daily`` row is a number without a
unit — and on a KGS workspace that unit is RUB for campaigns created before WB
moved the ad account on 2026-08-20 and KGS after. This phase asks WB once per
batch of campaigns (``plan_currency_probes``) and labels their unlabelled rows.

Cheap and idempotent: it reads only campaigns still missing a label, so a
second run asks nothing. A campaign WB answers for without a currency, or does
not answer for at all, stays unlabelled rather than guessed.
"""

from __future__ import annotations

import asyncio

from scripts.backfill.common import PhaseTotals
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries import WBAdvertisingClient
from src.modules.monitoring.repos import AdvertisingRepository
from src.modules.monitoring.services.ad_currency import plan_currency_probes
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def _backfill_ad_currency(
    tokens: WorkspaceTokenBundle, *, pause: float, totals: PhaseTotals
) -> None:
    """Label every unlabelled advertising row of one workspace from fullstats.

    Args:
        tokens: The workspace's decrypted WB credentials.
        pause: Seconds between calls, on top of the client's own gate.
        totals: Shared counters for the run's final report.
    """
    if not tokens.advertising:
        logger.warning("Workspace '%s' has no promotion token; ad currency skipped.", tokens.name)
        return

    async with AsyncSessionLocal() as session:
        missing = await AdvertisingRepository(session).campaigns_without_currency(
            workspace_id=tokens.workspace_id
        )
    probes = plan_currency_probes(missing)
    logger.info(
        "'%s': %d campaigns without a currency, %d fullstats calls.",
        tokens.name,
        len(missing),
        len(probes),
    )

    async with WBAdvertisingClient(settings, token=tokens.advertising) as client:
        for number, probe in enumerate(probes, start=1):
            try:
                stats = await client.fetch_full_stats(
                    campaign_ids=probe.campaign_ids, date_from=probe.begin, date_to=probe.end
                )
            except IntegrationError as exc:
                # One refused call costs its batch, not the walk; a re-run
                # picks the batch up again because its rows stay unlabelled.
                logger.warning("Ad currency probe %d failed for '%s': %s", number, tokens.name, exc)
                continue
            labelled = 0
            async with AsyncSessionLocal() as session:
                repo = AdvertisingRepository(session)
                for campaign in stats:
                    if campaign.currency:
                        labelled += await repo.label_campaign_currency(
                            workspace_id=tokens.workspace_id,
                            campaign_id=campaign.campaign_id,
                            currency=campaign.currency,
                        )
                await session.commit()
            totals.add("ad_rows_labelled", labelled)
            logger.info(
                "'%s' probe %d/%d (%s..%s, %d campaigns): %d rows labelled.",
                tokens.name,
                number,
                len(probes),
                probe.begin,
                probe.end,
                len(probe.campaign_ids),
                labelled,
            )
            if number < len(probes):
                await asyncio.sleep(pause)
