"""The daily review history across the fleet: ``monitoring.snapshot_reviews``.

It earns nothing on the day it runs — it exists so that a rating change can be
explained afterwards (see :mod:`src.modules.monitoring.models.reviews`). So the
rule for everything here is that it must never be the reason paying work waited:

* **Its own hour.** 19:40 MSK, scheduled in ``src.core.celery_app``: after the
  last daytime finance tick, away from the nightly block and the evening price
  top-up.
* **One run at a time.** A Redis lock across the whole fleet walk, so a slow
  evening never meets the next one.
* **Out of a first harvest's way.** While any workspace's first-run harvests may
  be running, the task puts itself back by twenty minutes, at most a few times.
  Those harvests are what the worker's memory ceiling was sized around.
* **Its own buckets.** The seller list is paced on the "Questions and reviews" bucket
  it shares only with the monthly `guide` capture; the storefront on one slow
  bucket shared by every workspace.
* **Only the workspaces that can.** A workspace with no "Questions and reviews" (or
  unified) token is skipped without a word — it is not a failure to have
  chosen not to grant a scope.
"""

from __future__ import annotations

from typing import Any

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.locks import single_flight
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries.clients import WBFeedbacksClient, WBStorefrontFeedbacksClient
from src.modules.monitoring.repos import ReviewRepository
from src.modules.monitoring.services.reviews import ReviewHistory
from src.modules.workspaces.contract import bootstrap_in_flight, load_workspace_token_bundles

logger = get_logger(__name__)

_LOCK_KEY = "monitoring:snapshot_reviews"
_LOCK_TTL_SECONDS = 120.0

#: How long to step aside for a first-run harvest, and how many times. An hour
#: in all: a bootstrap claim lasts fifteen minutes, so three postponements see
#: out anything but a stream of new sign-ups — and on that evening the history
#: runs anyway rather than not at all.
_POSTPONE_SECONDS = 20 * 60
_MAX_POSTPONEMENTS = 3


async def _snapshot_all(*, may_postpone: bool) -> dict[str, int] | None:
    """Run the review history for every workspace holding the scope, in turn.

    Args:
        may_postpone: Whether a first-run harvest in flight may still put this
            run back; ``False`` once the postponements are spent.

    Returns:
        Totals across the fleet, or ``None`` when the run should be postponed.
    """
    if may_postpone and await bootstrap_in_flight():
        return None
    totals = {
        "workspaces": 0,
        "skipped_no_token": 0,
        "failed": 0,
        "listed": 0,
        "events": 0,
        "vanished": 0,
        "snapshots": 0,
        "incomplete": 0,
    }
    async with single_flight(_LOCK_KEY, ttl_seconds=_LOCK_TTL_SECONDS, redis=get_redis()) as held:
        if not held:
            logger.info("Review history already running; this run is a no-op.")
            return totals
        async with AsyncSessionLocal() as session:
            bundles = await load_workspace_token_bundles(session)
        today = moscow_today()
        async with WBStorefrontFeedbacksClient(settings) as storefront:
            for bundle in bundles:
                if not bundle.feedbacks:
                    totals["skipped_no_token"] += 1
                    continue
                bind_workspace(bundle.workspace_id)
                try:
                    async with (
                        AsyncSessionLocal() as session,
                        WBFeedbacksClient(settings, token=bundle.feedbacks) as feedbacks,
                    ):
                        result = await ReviewHistory(
                            ReviewRepository(session),
                            commit=session.commit,
                            feedbacks=feedbacks,
                            storefront=storefront,
                            workspace_id=bundle.workspace_id,
                            today=today,
                        ).run()
                except Exception as exc:  # one workspace's failure is not the fleet's
                    logger.warning("Review history failed for '%s': %s", bundle.name, exc)
                    totals["failed"] += 1
                    continue
                totals["workspaces"] += 1
                totals["listed"] += result.listed
                totals["events"] += result.events
                totals["vanished"] += result.vanished
                totals["snapshots"] += result.snapshots
                totals["incomplete"] += int(not result.complete)
                logger.info(
                    "Review history for '%s': %d listed, %d events, %d vanished, "
                    "%d snapshots, complete=%s%s.",
                    bundle.name,
                    result.listed,
                    result.events,
                    result.vanished,
                    result.snapshots,
                    result.complete,
                    f", notes={result.notes}" if result.notes else "",
                )
        bind_workspace(None)
    return totals


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.snapshot_reviews",
    bind=True,
    max_retries=_MAX_POSTPONEMENTS,
)
def snapshot_reviews(self: Any) -> dict[str, int]:
    """Scheduled entrypoint: record today's ratings and review changes.

    Not on the shared retry policy: a WB failure is recorded per workspace and
    the next evening is the retry. The only re-run is the postponement.

    Returns:
        Fleet totals; ``{"postponed": 1}`` when it stepped aside.
    """
    if settings.wb_fake_harvest:
        # The synthetic harvest has no reviews to fake, and this path must not
        # reach WB from a developer's machine.
        return {"workspaces": 0}
    totals = run_task(_snapshot_all(may_postpone=self.request.retries < _MAX_POSTPONEMENTS))
    if totals is None:
        logger.info("A first-run harvest is in flight; review history postponed.")
        raise self.retry(countdown=_POSTPONE_SECONDS)
    return totals
