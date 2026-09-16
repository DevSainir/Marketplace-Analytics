"""One polling pass for one test: wire the runner, and run it.

Separated from the sweep that calls it and from the cabinet it reads, because
this is the only place that knows how a :class:`~..services.runner.RotationRunner`
is assembled — which repositories, which WB clients, and which of the reads are
per-cabinet rather than per-test. That wiring is most of the file and none of the
sweep's business.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

import httpx

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.integrations.wildberries import WBAdvertisingClient, WBContentClient
from src.integrations.wildberries.schemas import WBAdvCampaignStats, WBAdvertV2
from src.modules.ab_tests.models import AbTest
from src.modules.ab_tests.repos import (
    AbTestRepository,
    CampaignFacts,
    CampaignRepository,
    ExposureRepository,
    SnapshotRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.budget import AdsState, read_state
from src.modules.ab_tests.services.campaigns import classify
from src.modules.ab_tests.services.collection import CampaignDays, counters_by_campaign_day
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.runner import RotationRunner
from src.modules.ab_tests.services.storage import build_media_store
from src.modules.ab_tests.services.witness import PhotoWitness
from src.modules.ab_tests.tasks.cabinet import Cabinet

logger = get_logger(__name__)


async def poll_one(
    test: AbTest,
    *,
    cabinet: Cabinet,
    now: datetime,
    days: Sequence[date],
) -> str | None:
    """Run one polling pass for one test in its own transaction.

    A transaction per test so a WB failure on one cannot roll back the window
    another has just recorded.

    Args:
        test: The running test, as listed by the sweep.
        cabinet: Its workspace's shared reads for this pass.
        now: The moment of this pass.
        days: Advertising days to read.

    Returns:
        The action taken, or ``None`` when the test was skipped.
    """
    async with AsyncSessionLocal() as session:
        repo = AbTestRepository(session)
        loaded = await repo.get(workspace_id=test.workspace_id, test_id=test.id)
        if loaded is None:  # deleted between the listing and now
            return None

        async with (
            WBAdvertisingClient(settings, token=cabinet.advertising) as adv_client,
            WBContentClient(settings, token=cabinet.content) as content_client,
            # Its own client: the basket CDN is public and unauthenticated, and
            # carries none of the headers, tokens or rate gating a WB API client
            # exists to apply.
            httpx.AsyncClient() as photo_client,
        ):
            witness = PhotoWitness(client=photo_client)

            async def _reader(
                nm_id: int,
                wanted: Sequence[date],
                stats: list[WBAdvCampaignStats] = cabinet.stats,
            ) -> CampaignDays:
                """Slice this test's rows out of the workspace's one answer.

                No request: the fullstats reply already carries a per-SKU
                breakdown of every campaign it was asked about, so a hundred
                tests read a hundred slices of the same download.

                The campaigns are kept apart rather than summed — see
                :mod:`..services.collection`.

                Bound as a DEFAULT rather than captured: the closure outlives
                the loop iteration it was defined in, and a free reference would
                resolve to whichever test the sweep reached last.
                """
                days = set(wanted)
                per_campaign = counters_by_campaign_day(stats, nm_id=nm_id)
                return {
                    campaign_id: kept
                    for campaign_id, counters in per_campaign.items()
                    if (kept := {day: value for day, value in counters.items() if day in days})
                }

            async def _remember(
                campaign_ids: Sequence[int],
                at: datetime,
                register: CampaignRepository = CampaignRepository(session),
                adverts: list[WBAdvertV2] = cabinet.adverts,
            ) -> None:
                """Name the campaigns this pass read, for the page to label.

                Resolved against the workspace's one listing, which is where
                both the name and the kind live. A campaign WB no longer lists
                — archived mid-test — keeps whatever the register already holds
                for it, because an upsert of «unknown» over a real name would
                lose the only copy of it there is.
                """
                known = {advert.campaign_id: advert for advert in adverts}
                facts = [
                    CampaignFacts(
                        campaign_id=campaign_id,
                        name=known[campaign_id].settings.name if campaign_id in known else None,
                        kind=(str(classify(known[campaign_id])) if campaign_id in known else None),
                    )
                    for campaign_id in campaign_ids
                ]
                await register.remember(test_id=test.id, seen=facts, at=at)

            async def _ads(
                nm_id: int,
                client: WBAdvertisingClient = adv_client,
                adverts: list[WBAdvertV2] = cabinet.adverts,
            ) -> AdsState:
                """Ask what this card's advertising is doing.

                The listing is the workspace's; only the budget of a serving
                campaign is a fresh request, and only when a swap is due.
                """
                return await read_state(client=client, adverts=adverts, nm_id=nm_id)

            async def _photo(
                nm_id: int,
                seen: PhotoWitness = witness,
                urls: dict[int, str] = cabinet.photos,
            ) -> datetime | None:
                """When did the storefront last publish this card's main photo?

                Bound as defaults for the same reason `_reader` is: the closure
                outlives the iteration that defined it.
                """
                return await seen.observe(urls.get(nm_id, ""))

            async def _confirm(
                nm_id: int,
                was: datetime | None,
                seen: PhotoWitness = witness,
                urls: dict[int, str] = cabinet.photos,
            ) -> datetime | None:
                """Wait for the storefront to show the install we just made."""
                return await seen.confirm_install(urls.get(nm_id, ""), was=was)

            runner = RotationRunner(
                tests=repo,
                exposures=ExposureRepository(session),
                windows=WindowRepository(session),
                snapshots=SnapshotRepository(session),
                installer=VariantInstaller(
                    # Not the api's shared store: this runs on a loop the task
                    # closes when it returns, and a socket pooled across that
                    # boundary is what killed a whole night's harvest twice
                    # (see src.core.tasks). One photo per swap does not need it.
                    content_client=content_client,
                    media_store=build_media_store(settings),
                ),
                read_counters=_reader,
                read_ads=_ads,
                read_photo=_photo,
                confirm_install=_confirm,
                remember_campaigns=_remember,
            )
            outcome = await runner.poll(loaded, days=days, now=now)

        await session.commit()

    # Neither pause is an action — each is a HOLD with a reason — so they are
    # reported separately rather than by overloading the word the sweep counts
    # by. The two are kept apart because only one of them ever resumes itself.
    if outcome.photo_conflict:
        return "photo_conflict"
    return "paused" if outcome.paused else str(outcome.action)


__all__ = ["poll_one"]
