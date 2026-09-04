"""Celery entrypoint for the rotation poller.

Runs every few minutes, not once a night. WB's advertising report has a one-day
*reporting* grain — ``fullstats`` refuses a shorter interval — but it serves the
CURRENT day and moves within minutes, so the traffic of any interval is the
difference between two reads. That is what lets a photo turn over several times
a day.

**Why a fixed interval rather than one adapted to traffic.** One fullstats call
carries up to 50 campaign ids and answers for every SKU inside them, so the cost
of a pass does not grow with the number of tests or with how fast they are
gathering impressions — it grows only with the number of workspaces. WB's
published budget for the endpoint is 3 requests per minute per seller; polling
every five minutes spends about 7% of it. Adapting the cadence to impressions
would save nothing measurable and would make the trigger's resolution vary
between tests.

The budget is shared with the nightly harvest through a Redis token bucket
(``advertising_rate_gate``), so the two queue against one allowance instead of
discovering each other through 429s.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient, WBContentClient
from src.modules.ab_tests.deps import get_media_store
from src.modules.ab_tests.models import AbTest
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    SnapshotRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.collection import Counters, counters_by_day, days_to_read
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.runner import RotationRunner
from src.modules.monitoring.contract import load_campaign_ids_for_workspace
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)

#: WB caps ``ids`` at 50 per fullstats request.
_CAMPAIGN_BATCH = 50


async def _read_counters(
    client: WBAdvertisingClient,
    campaign_ids: Sequence[int],
    nm_id: int,
    days: Sequence[date],
) -> dict[date, Counters]:
    """Read one SKU's cumulative counters for the given days.

    Args:
        client: Advertising client, already paced by the shared gate.
        campaign_ids: Campaigns to ask about; chunked to WB's 50-id limit.
        nm_id: The SKU under test.
        days: Advertising days to cover.

    Returns:
        ``{day: cumulative counters}`` for this SKU.
    """
    if not campaign_ids or not days:
        return {}

    totals: dict[date, Counters] = {}
    for start in range(0, len(campaign_ids), _CAMPAIGN_BATCH):
        chunk = list(campaign_ids[start : start + _CAMPAIGN_BATCH])
        campaigns = await client.fetch_full_stats(
            campaign_ids=chunk, date_from=min(days), date_to=max(days)
        )
        for day, counters in counters_by_day(campaigns, nm_id=nm_id).items():
            totals[day] = totals.get(day, Counters()) + counters
    return totals


async def _poll_one(test: AbTest, *, now: datetime, days: Sequence[date]) -> str | None:
    """Run one polling pass for one test in its own transaction.

    A transaction per test so a WB failure on one cannot roll back the window
    another has just recorded.

    Args:
        test: The running test, as listed by the sweep.
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

        bundle = await load_workspace_token_bundle(session, workspace_id=test.workspace_id)
        advertising = (bundle.advertising or "") if bundle else ""
        content = ((bundle.content or bundle.analytics) if bundle else "") or ""
        if not advertising or not content:
            logger.warning(
                "ab_tests: workspace %s lacks an advertising or content token; skipping %s",
                test.workspace_id,
                test.id,
            )
            return None

        campaign_ids = await load_campaign_ids_for_workspace(
            session, workspace_id=test.workspace_id
        )

        async with (
            WBAdvertisingClient(settings, token=advertising) as adv_client,
            WBContentClient(settings, token=content) as content_client,
        ):

            async def _reader(
                nm_id: int,
                wanted: Sequence[date],
                client: WBAdvertisingClient = adv_client,
                ids: Sequence[int] = campaign_ids,
            ) -> dict[date, Counters]:
                """Read this test's counters, with its own client and campaigns.

                Both are bound as DEFAULTS rather than captured: the closure
                outlives the loop iteration it was defined in, and a free
                reference would resolve to whichever test the sweep reached
                last.
                """
                return await _read_counters(client, ids, nm_id, wanted)

            runner = RotationRunner(
                tests=repo,
                exposures=ExposureRepository(session),
                windows=WindowRepository(session),
                snapshots=SnapshotRepository(session),
                installer=VariantInstaller(
                    content_client=content_client, media_store=get_media_store()
                ),
                read_counters=_reader,
            )
            outcome = await runner.poll(loaded, days=days, now=now)

        await session.commit()

    return str(outcome.action)


async def _poll_all() -> dict[str, int]:
    """Poll every running test once.

    Returns:
        ``{"tests": n, "rotated": n, "completed": n, "failed": n}``.
    """
    now = datetime.now(UTC)
    days = list(days_to_read(moscow_today()))

    async with AsyncSessionLocal() as session:
        tests = await AbTestRepository(session).list_advanceable()

    counters = {"tests": len(tests), "rotated": 0, "completed": 0, "failed": 0}

    for test in tests:
        try:
            action = await _poll_one(test, now=now, days=days)
        except IntegrationError as exc:
            counters["failed"] += 1
            logger.warning("ab_tests: test %s could not be polled: %s", test.id, exc)
            continue

        if action in {"install", "advance"}:
            counters["rotated"] += 1
        elif action == "complete":
            counters["completed"] += 1

    if counters["tests"]:
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
