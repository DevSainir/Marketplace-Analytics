"""What one workspace's tests share for the duration of a polling pass.

Its own module because it is the difference between a cost that grows with the
number of tests and one that does not. A fullstats answer covers every SKU inside
the campaigns it was asked about, so a cabinet's advertising is read ONCE and
every test in it takes its own slice; the same goes for the campaign listing and
for the catalogue's photo URLs. Assembling that is a job with nothing to do with
running a pass, which is what :mod:`.passes` does with the result.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.integrations.wildberries import WBAdvertisingClient
from src.integrations.wildberries.schemas import WBAdvCampaignStats, WBAdvertV2
from src.modules.ab_tests.models import AbTest
from src.modules.ab_tests.services.campaigns import campaigns_for_sku
from src.modules.monitoring.contract import load_campaign_ids_for_workspace, load_card_photos
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)

#: WB caps ``ids`` at 50 per fullstats request.
CAMPAIGN_BATCH = 50


@dataclass(frozen=True)
class Cabinet:
    """Everything one workspace's tests share for the duration of a pass.

    Assembled once and handed to every test in the workspace. The advertising
    reads live here rather than in the per-test pass because that is the whole
    difference between a cost that grows with tests and one that does not.
    """

    #: Advertising-scope token, for campaign listings and budgets.
    advertising: str
    #: Content-scope token, for installing a photo on the card.
    content: str
    #: WB's campaign listing for the account.
    adverts: list[WBAdvertV2]
    #: One fullstats answer covering every campaign any of these tests names.
    #: Carries a per-SKU breakdown, so each test reads its own rows out of it.
    stats: list[WBAdvCampaignStats]
    #: ``{nm_id: main-photo URL}`` from monitoring's catalogue — what the photo
    #: witness asks the storefront about. A SKU with no stored photo is absent,
    #: and its test simply goes unchecked: the guard's whole contract is that
    #: not knowing means carrying on.
    photos: dict[int, str]


async def read_all_stats(
    client: WBAdvertisingClient, campaign_ids: Sequence[int], days: Sequence[date]
) -> list[WBAdvCampaignStats]:
    """Read one workspace's advertising for the whole pass.

    Args:
        client: Advertising client, already paced by the shared gate.
        campaign_ids: Every campaign any of the workspace's tests names.
        days: Advertising days to cover — the same window for all of them.

    Returns:
        The parsed campaign nodes, concatenated across id batches. Empty when
        there is nothing to ask about.
    """
    if not campaign_ids or not days:
        return []

    stats: list[WBAdvCampaignStats] = []
    for start in range(0, len(campaign_ids), CAMPAIGN_BATCH):
        stats.extend(
            await client.fetch_full_stats(
                campaign_ids=list(campaign_ids[start : start + CAMPAIGN_BATCH]),
                date_from=min(days),
                date_to=max(days),
            )
        )
    return stats


async def prepare_cabinet(
    workspace_id: uuid.UUID, tests: Sequence[AbTest], days: Sequence[date]
) -> Cabinet | None:
    """Do a workspace's advertising reads once, for all of its tests.

    Args:
        workspace_id: The workspace being polled.
        tests: Its running tests.
        days: Advertising days to cover.

    Returns:
        The shared context, or ``None`` when the workspace has no usable
        tokens — in which case none of its tests can be polled at all.
    """
    async with AsyncSessionLocal() as session:
        bundle = await load_workspace_token_bundle(session, workspace_id=workspace_id)
        advertising = (bundle.advertising or "") if bundle else ""
        content = ((bundle.content or bundle.analytics) if bundle else "") or ""
        if not advertising or not content:
            logger.warning(
                "ab_tests: workspace %s lacks an advertising or content token; "
                "skipping its %s test(s)",
                workspace_id,
                len(tests),
            )
            return None
        # Only the cards under test. A cabinet advertising four hundred SKUs
        # while testing three of them was pulling in every campaign it had ever
        # run, and every fifty of those is another fullstats batch and another
        # twenty seconds of the pass.
        harvested = await load_campaign_ids_for_workspace(
            session,
            workspace_id=workspace_id,
            nm_ids=sorted({test.nm_id for test in tests}),
        )
        # One query for the cabinet's catalogue thumbnails. The URL is the only
        # thing the photo witness needs, and monitoring owns the catalogue —
        # hence the contract loader rather than a join this module may not make.
        photos = await load_card_photos(session, workspace_id=workspace_id)

    async with WBAdvertisingClient(settings, token=advertising) as client:
        adverts = await client.list_adverts()
        # The union across every test here. Campaigns overlap heavily — the
        # harvested ids are workspace-wide — so a hundred tests usually resolve
        # to the same one or two batches of fifty.
        campaign_ids = sorted(
            {
                campaign_id
                for test in tests
                for campaign_id in campaigns_for_sku(adverts, nm_id=test.nm_id, known=harvested)
            }
        )
        stats = await read_all_stats(client, campaign_ids, days)

    logger.info(
        "ab_tests: workspace %s — %s test(s), %s campaign(s), %s fullstats call(s)",
        workspace_id,
        len(tests),
        len(campaign_ids),
        -(-len(campaign_ids) // CAMPAIGN_BATCH),
    )
    return Cabinet(
        advertising=advertising,
        content=content,
        adverts=adverts,
        stats=stats,
        photos=photos,
    )


__all__ = ["CAMPAIGN_BATCH", "Cabinet", "prepare_cabinet", "read_all_stats"]
