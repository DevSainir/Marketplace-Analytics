"""Celery entrypoint for the rotation poller.

Runs every few minutes, not once a night. WB's advertising report has a one-day
*reporting* grain — ``fullstats`` refuses a shorter interval — but it serves the
CURRENT day and moves within minutes, so the traffic of any interval is the
difference between two reads. That is what lets a photo turn over several times
a day.

**One advertising read per workspace, not per test.** A fullstats answer covers
every SKU inside the campaigns it was asked about — the per-day rows carry an
``nms[]`` breakdown — so one call serves every test in a workspace and each test
takes its own slice of it. This used to be a call per test, which read the same
answer over and over and, worse, did not scale: the endpoint's bucket is one
token per 20 seconds PER SELLER TOKEN, so around the seventh test in a cabinet
the queue passed the 120-second cap and the rest were simply not polled that
pass. They did not fail visibly — they just stopped advancing, which on the
screen looks like a test that has stalled for no reason.

So the cost of a pass grows with the number of **workspaces**, and with the
number of campaigns only in 50-id steps. WB's published budget for the endpoint
is 3 requests per minute per seller; a pass now spends one or two of them
whether the cabinet holds one test or two hundred.

**Why a fixed interval rather than one adapted to traffic.** Adapting the
cadence to impressions would save nothing measurable now that the cost is flat
in the number of tests, and would make the trigger's resolution vary between
them.

The budget is shared with the nightly harvest through a Redis token bucket
(``advertising_rate_gate``), so the two queue against one allowance instead of
discovering each other through 429s.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient, WBContentClient
from src.integrations.wildberries.schemas import WBAdvCampaignStats, WBAdvertV2
from src.modules.ab_tests.deps import get_media_store
from src.modules.ab_tests.models import AbTest
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    SnapshotRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.budget import AdsState, read_state
from src.modules.ab_tests.services.campaigns import campaigns_for_sku
from src.modules.ab_tests.services.collection import Counters, counters_by_day, days_to_read
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.runner import RotationRunner
from src.modules.monitoring.contract import load_campaign_ids_for_workspace
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)

#: WB caps ``ids`` at 50 per fullstats request.
_CAMPAIGN_BATCH = 50


@dataclass(frozen=True)
class _Cabinet:
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


async def _read_all_stats(
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
    for start in range(0, len(campaign_ids), _CAMPAIGN_BATCH):
        stats.extend(
            await client.fetch_full_stats(
                campaign_ids=list(campaign_ids[start : start + _CAMPAIGN_BATCH]),
                date_from=min(days),
                date_to=max(days),
            )
        )
    return stats


async def _prepare_cabinet(
    workspace_id: uuid.UUID, tests: Sequence[AbTest], days: Sequence[date]
) -> _Cabinet | None:
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
        harvested = await load_campaign_ids_for_workspace(session, workspace_id=workspace_id)

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
        stats = await _read_all_stats(client, campaign_ids, days)

    logger.info(
        "ab_tests: workspace %s — %s test(s), %s campaign(s), %s fullstats call(s)",
        workspace_id,
        len(tests),
        len(campaign_ids),
        -(-len(campaign_ids) // _CAMPAIGN_BATCH),
    )
    return _Cabinet(advertising=advertising, content=content, adverts=adverts, stats=stats)


async def _poll_one(
    test: AbTest,
    *,
    cabinet: _Cabinet,
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
        ):

            async def _reader(
                nm_id: int,
                wanted: Sequence[date],
                stats: list[WBAdvCampaignStats] = cabinet.stats,
            ) -> dict[date, Counters]:
                """Slice this test's rows out of the workspace's one answer.

                No request: the fullstats reply already carries a per-SKU
                breakdown of every campaign it was asked about, so a hundred
                tests read a hundred slices of the same download.

                Bound as a DEFAULT rather than captured: the closure outlives
                the loop iteration it was defined in, and a free reference would
                resolve to whichever test the sweep reached last.
                """
                counters = counters_by_day(stats, nm_id=nm_id)
                return {day: value for day, value in counters.items() if day in set(wanted)}

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

            runner = RotationRunner(
                tests=repo,
                exposures=ExposureRepository(session),
                windows=WindowRepository(session),
                snapshots=SnapshotRepository(session),
                installer=VariantInstaller(
                    content_client=content_client, media_store=get_media_store()
                ),
                read_counters=_reader,
                read_ads=_ads,
            )
            outcome = await runner.poll(loaded, days=days, now=now)

        await session.commit()

    # «Paused» is not an action — it is a HOLD with a reason — so it is reported
    # separately rather than by overloading the word the sweep counts by.
    return "paused" if outcome.paused else str(outcome.action)


async def _resume_paused(adverts_by_workspace: dict[uuid.UUID, list[WBAdvertV2]]) -> int:
    """Start any test the rotation paused whose campaign is serving again.

    The seller switched their advertising back on; nobody should have to
    remember that a test was waiting for it. Tests the SELLER paused are not in
    this list and are never touched.

    Args:
        adverts_by_workspace: Per-pass cache of WB's campaign listing, shared
            with the polling sweep so a workspace is listed once.

    Returns:
        How many tests were resumed.
    """
    async with AsyncSessionLocal() as session:
        paused = await AbTestRepository(session).list_ads_paused()

    resumed = 0
    for test in paused:
        async with AsyncSessionLocal() as session:
            repo = AbTestRepository(session)
            loaded = await repo.get(workspace_id=test.workspace_id, test_id=test.id)
            if loaded is None or not loaded.paused_by_ads:
                continue

            bundle = await load_workspace_token_bundle(session, workspace_id=test.workspace_id)
            advertising = (bundle.advertising or "") if bundle else ""
            if not advertising:
                continue

            async with WBAdvertisingClient(settings, token=advertising) as client:
                if test.workspace_id not in adverts_by_workspace:
                    adverts_by_workspace[test.workspace_id] = await client.list_adverts()
                state = await read_state(
                    client=client,
                    adverts=adverts_by_workspace[test.workspace_id],
                    nm_id=test.nm_id,
                )

            if state is AdsState.SERVING:
                await repo.resume_after_ads(test=loaded)
                await session.commit()
                resumed += 1
                logger.info(
                    "ab_tests: campaign is serving nm %s again; test %s resumes",
                    test.nm_id,
                    test.id,
                )
    return resumed


async def _poll_all() -> dict[str, int]:
    """Poll every running test once, and wake the ones waiting on a campaign.

    Returns:
        ``{"tests": n, "rotated": n, "paused": n, "resumed": n, "failed": n}``.
    """
    now = datetime.now(UTC)
    days = list(days_to_read(moscow_today()))

    async with AsyncSessionLocal() as session:
        tests = await AbTestRepository(session).list_advanceable()

    counters = {
        "tests": len(tests),
        "rotated": 0,
        "paused": 0,
        "resumed": 0,
        "failed": 0,
    }

    # Grouped by workspace because that is the unit the advertising reads are
    # priced in: WB's bucket is per seller token, so a hundred tests in one
    # cabinet share one allowance while a hundred cabinets do not compete.
    by_workspace: dict[uuid.UUID, list[AbTest]] = defaultdict(list)
    for test in tests:
        by_workspace[test.workspace_id].append(test)

    # Kept across the sweep so `_resume_paused` reuses the same listings, and
    # dropped when the pass ends: a campaign started between two passes has to
    # be visible to the next one.
    adverts_by_workspace: dict[uuid.UUID, list[WBAdvertV2]] = {}

    for workspace_id, workspace_tests in by_workspace.items():
        try:
            cabinet = await _prepare_cabinet(workspace_id, workspace_tests, days)
        except IntegrationError as exc:
            counters["failed"] += len(workspace_tests)
            logger.warning("ab_tests: workspace %s could not be read: %s", workspace_id, exc)
            continue

        if cabinet is None:
            counters["failed"] += len(workspace_tests)
            continue
        adverts_by_workspace[workspace_id] = cabinet.adverts

        for test in workspace_tests:
            try:
                action = await _poll_one(test, cabinet=cabinet, now=now, days=days)
            except IntegrationError as exc:
                counters["failed"] += 1
                logger.warning("ab_tests: test %s could not be polled: %s", test.id, exc)
                continue

            if action in {"install", "advance"}:
                counters["rotated"] += 1
            elif action == "paused":
                counters["paused"] += 1

    # After the sweep, not before: a test paused by this very pass must not be
    # resumed by it, and the listing cache is warm by now.
    counters["resumed"] = await _resume_paused(adverts_by_workspace)

    if counters["tests"] or counters["resumed"]:
        logger.info("ab_tests: polling pass %s", counters)
    return counters


@celery_app.task(  # type: ignore[untyped-decorator]
    name="ab_tests.poll_rotations",
    bind=False,
)
def poll_rotations() -> dict[str, int]:
    """Scheduled entrypoint: close each running test's interval and rotate if due.

    Returns:
        Per-pass counters, as :func:`_poll_all` returns them.
    """
    return run_task(_poll_all())


__all__ = ["poll_rotations"]
