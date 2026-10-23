"""Celery entrypoint for the rotation poller, and the sweep it runs.

Three modules, split when the file passed the repo's 500-line ceiling: what a
workspace shares for one pass is in :mod:`.cabinet`, wiring and running one test's
pass is in :mod:`.passes`, and what stays here is the sweep — which tests to
poll, in what order, how many at once, and which of them to wake up again.

Runs every few minutes, not once a night. WB's advertising report has a one-day
*reporting* grain — ``fullstats`` refuses a shorter interval — but it serves the
CURRENT day and moves within minutes, so the traffic of any interval is the
difference between two reads. That is what lets a photo turn over several times
a day.

**One advertising read per workspace, not per test.** A fullstats answer covers
every SKU inside the campaigns it was asked about — the per-day rows carry an
``nms[]`` breakdown — so one call serves every test in a workspace and each test
takes its own slice of it.

This used to be a call per test, and the cost was wall-clock rather than
failure. The bucket is one token per 20 seconds PER SELLER TOKEN, and the sweep
is sequential, so a hundred tests in one workspace did not error — they took a
hundred turns of the bucket, about half an hour, for a pass scheduled every
five minutes. Passes then overlap and every test's window stretches to whenever
the sweep next reaches it.

What actually bounds a pass is therefore the number of **50-id batches** it
sends, not the number of tests. The first batch on each token is free — the
bucket starts full and every workspace has its own — and each further batch costs
20 seconds of the pass's five minutes. A workspace whose campaigns fit in one
batch costs no waiting at all, however many tests it holds.

**Why a fixed interval rather than one adapted to traffic.** Adapting the
cadence to impressions would save nothing measurable now that the cost is flat
in the number of tests, and would make the trigger's resolution vary between
them.

The budget is shared with the nightly harvest through a Redis token bucket
(``advertising_rate_gate``), so the two queue against one allowance instead of
discovering each other through 429s.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAdvertisingClient
from src.integrations.wildberries.schemas import WBAdvertV2
from src.modules.ab_tests.models import AbTest, AbTestStatus
from src.modules.ab_tests.repos import AbTestRepository
from src.modules.ab_tests.services.budget import AdsState, read_state
from src.modules.ab_tests.services.collection import days_to_read
from src.modules.ab_tests.tasks.cabinet import prepare_cabinet
from src.modules.ab_tests.tasks.passes import poll_one
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)


async def _gather_bounded[T, R](
    items: Sequence[T],
    run: Callable[[T], Awaitable[R]],
    *,
    limit: int,
) -> list[R]:
    """Run ``run`` over ``items`` concurrently, at most ``limit`` at a time.

    The bound is the point, not the concurrency. Workspaces are independent as far
    as WB is concerned, but they are not independent as far as our database is:
    each one holds a session while it reads its tokens, and an unbounded
    ``gather`` over five hundred of them would ask this process's pool — ten
    connections plus twenty of overflow — for five hundred at once and stall
    every one of them behind the pool's own timeout.

    Args:
        items: What to run over.
        run: The coroutine function to run for each.
        limit: How many may be in flight at once.

    Returns:
        The results, in the order the items were given.
    """
    gate = asyncio.Semaphore(limit)

    async def _guarded(item: T) -> R:
        async with gate:
            return await run(item)

    return list(await asyncio.gather(*(_guarded(item) for item in items)))


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
            # The status as well as the flag: finishing a test does not clear
            # `paused_by_ads`, so a test finished after the listing still carries
            # it, and resuming that would restart a rotation the seller ended.
            if (
                loaded is None
                or not loaded.paused_by_ads
                or loaded.status != AbTestStatus.PAUSED.value
            ):
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
        ``{"tests": n, "rotated": n, "paused": n, "photo_conflict": n,
        "resumed": n, "failed": n}``.
    """
    now = datetime.now(UTC)
    days = list(days_to_read(moscow_today()))

    async with AsyncSessionLocal() as session:
        tests = await AbTestRepository(session).list_advanceable()

    counters = {
        "tests": len(tests),
        "rotated": 0,
        "paused": 0,
        # Counted apart from `paused` because it is the one stop nothing here
        # will undo: a conflict waits for the seller, not for a campaign.
        "photo_conflict": 0,
        "resumed": 0,
        "failed": 0,
    }

    # Grouped by workspace because that is the unit the advertising reads are
    # priced in: WB's bucket is per seller token, so a hundred tests in one
    # workspace share one allowance while a hundred workspaces do not compete.
    by_workspace: dict[uuid.UUID, list[AbTest]] = defaultdict(list)
    for test in tests:
        by_workspace[test.workspace_id].append(test)

    # Kept across the sweep so `_resume_paused` reuses the same listings, and
    # dropped when the pass ends: a campaign started between two passes has to
    # be visible to the next one.
    adverts_by_workspace: dict[uuid.UUID, list[WBAdvertV2]] = {}

    async def _sweep_cabinet(
        workspace_id: uuid.UUID, workspace_tests: list[AbTest]
    ) -> dict[str, int]:
        """Poll one workspace's tests, reporting what happened to them.

        Returns its own counters rather than mutating shared ones: the caller
        runs these concurrently, and a dict updated from several coroutines is
        a race waiting for the first slow WB call to expose it.
        """
        tally = {"rotated": 0, "paused": 0, "photo_conflict": 0, "failed": 0}
        try:
            cabinet = await prepare_cabinet(workspace_id, workspace_tests, days)
        except IntegrationError as exc:
            logger.warning("ab_tests: workspace %s could not be read: %s", workspace_id, exc)
            tally["failed"] += len(workspace_tests)
            return tally

        if cabinet is None:
            tally["failed"] += len(workspace_tests)
            return tally
        adverts_by_workspace[workspace_id] = cabinet.adverts

        # Tests WITHIN a workspace stay sequential. They share one rate
        # bucket and one transaction-per-test discipline, so running them
        # concurrently would win nothing and would put several of this
        # workspace's sessions in flight at once.
        for test in workspace_tests:
            try:
                action = await poll_one(test, cabinet=cabinet, now=now, days=days)
            except IntegrationError as exc:
                tally["failed"] += 1
                logger.warning("ab_tests: test %s could not be polled: %s", test.id, exc)
                continue

            if action in {"install", "advance"}:
                tally["rotated"] += 1
            elif action == "paused":
                tally["paused"] += 1
            elif action == "photo_conflict":
                tally["photo_conflict"] += 1
        return tally

    # Concurrently, because the rate buckets are independent — one per seller
    # token — so a workspace's twenty-second wait for a token is twenty seconds
    # during which every other workspace can be working. A sequential loop turned
    # independent waits into a queue nothing asked for.
    tallies = await _gather_bounded(
        list(by_workspace.items()),
        lambda pair: _sweep_cabinet(*pair),
        limit=settings.ab_tests_poll_concurrency,
    )
    for tally in tallies:
        for key, value in tally.items():
            counters[key] += value

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
