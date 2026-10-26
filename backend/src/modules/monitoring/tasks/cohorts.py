"""The buyout-cohort refresh: re-read maturing order-date cohorts, day by day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

# Sync on purpose: the lock outlives the event loop `run_task` builds and tears down.
from redis import Redis as SyncRedis  # noqa: TID251
from redis.exceptions import LockError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.observability.metrics import FUNNEL_GAP_DAYS
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import build_analytics_client
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    AdvertisingRepository,
    AdvertisingSearchRepository,
    AdvertisingWriteOffRepository,
    CampaignRepository,
    FunnelRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.monitoring.tasks.funnel_gaps import announce_funnel_gaps, heal_funnel_gaps
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)

#: How far back the cohort pass re-reads order-date cohorts. "Buyout rate"
#: for display day D averages the cohorts of ``[D-21, D-7]``, and a cohort's
#: deliveries keep being accepted/refused for ~3 weeks, so every cohort that a
#: current display day can still reach must be re-read until it settles.
#:
#: This CANNOT be folded into the funnel harvest: the daily history endpoint
#: only serves the last 7 days (HTTP 400 beyond that), so it can never revisit
#: a maturing cohort, and it carries no cancel count at all.
COHORT_REFRESH_DAYS = 22

#: Distributed-lock name preventing overlapping cohort passes.
_COHORT_LOCK_NAME = "monitoring:refresh_buyout_cohorts:lock"
_COHORT_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60


async def _refresh_workspace_cohorts(
    tokens: WorkspaceTokenBundle,
    days: int,
    on_day: Callable[[int, int], None] | None = None,
) -> int:
    """Re-read one workspace's maturing buyout/cancel cohorts, day by day.

    The aggregate endpoint takes a period, not a series, so one call per cohort
    day is unavoidable — but each call answers for the seller's WHOLE catalogue
    (WB ignores the ``nmIDs`` filter), so this is ``days`` requests per
    workspace regardless of SKU count, not ``days x SKUs``.

    Days are fetched sequentially and failures are isolated per day: this
    surface is rate-limited, and a 429 on one cohort must not cost the others.
    The pacing itself is the client's: :class:`WBAnalyticsClient` holds a
    Redis-backed token bucket per endpoint, so the loop below simply asks for
    the next day and the gate makes it wait its turn. That is what keeps a
    22-day pass to its ~7 minutes instead of the 65+ minutes it took on
    2026-07-30, when the loop fired each day the instant the previous returned
    and every request landed in an empty bucket.

    The gate is shared across processes, so this pass no longer starves an
    interactive "Refresh" running beside it — the two queue against the same
    budget instead of racing for it.

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: How many days back from yesterday to re-read.
        on_day: Called after each cohort day is attempted, with ``(done,
            total)``. This loop is the long pole in an interactive refresh —
            22 paced requests, ~7 minutes — so it is the only place that can
            say how far along it is. Called for failed days too: the pass moves
            on from them, and a bar that stalled on a WB hiccup would report a
            run as stuck when it is not.

    Returns:
        The number of cohort days refreshed across the window.

    Raises:
        IntegrationError: When WB served no day at all. A pass that refreshed
            nothing used to log "Refreshed 0 cohort days" at INFO and exit
            successfully, which is how "Buyout rate" could quietly stop
            maturing; failing hands it to the task retry policy instead.
    """
    if not tokens.analytics:
        logger.warning("Workspace '%s' has no analytics token; skipping cohorts.", tokens.name)
        return 0

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    refreshed = 0
    served = 0
    async with build_analytics_client(settings, token=tokens.analytics) as analytics_client:
        for offset in range(days):
            day = end - timedelta(days=offset)
            try:
                rows = await analytics_client.fetch_funnel_cohort_day(day=day)
            except Exception as exc:  # isolate one cohort day from the rest
                logger.warning("Cohort refresh failed for %s: %s", day, exc)
                if on_day is not None:
                    on_day(offset + 1, days)
                continue
            served += 1
            async with AsyncSessionLocal() as session:
                service = _cohort_ingestion_service(session)
                refreshed += await service.ingest_funnel_cohorts(day, rows)
                # The same response carries each card's buyer rating, which is
                # the card's state now rather than the cohort day's — so it is
                # read once, off the freshest day the pass is served.
                if served == 1:
                    await service.ingest_feedback_ratings(rows, workspace_id=tokens.workspace_id)
                await session.commit()
            if on_day is not None:
                on_day(offset + 1, days)
    if served == 0:
        raise IntegrationError(
            f"WB served none of the {days} cohort days for workspace '{tokens.name}'; "
            "the buyout rate would silently stop maturing."
        )
    logger.info(
        "Refreshed %d cohort days for workspace '%s' (%d of %d days served).",
        refreshed,
        tokens.name,
        served,
        days,
    )
    return refreshed


def _cohort_ingestion_service(session: AsyncSession) -> IngestionService:
    """Build an IngestionService for the cohort pass.

    Only ``funnel_repo`` and ``product_card_repo`` (the ratings) are exercised,
    but the service wires its full repository graph — the others are
    constructed and left unused.
    """
    return IngestionService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
        advertising_cluster_repo=AdvertisingClusterRepository(session),
        advertising_write_off_repo=AdvertisingWriteOffRepository(session),
        price_repo=PriceRepository(session),
        sale_repo=SaleRepository(session),
    )


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.refresh_buyout_cohorts",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def refresh_buyout_cohorts(days: int = COHORT_REFRESH_DAYS) -> dict[str, int]:
    """Scheduled entrypoint: re-read every workspace's maturing buyout cohorts.

    Separate from ``harvest_all`` on purpose. The pass is catalogue-wide by
    construction (one call answers for every SKU), so running it per harvested
    SKU would repeat identical work; and it costs ``days`` sequential
    rate-limited requests, which would add minutes to the interactive
    "Refresh" press that ``harvest_sku_window`` serves.

    Args:
        days: How many days back from yesterday to re-read.

    Returns:
        ``{"cohort_rows": n}``, or ``{"skipped_already_running": 1}`` when
        another pass holds the lock.
    """
    redis = SyncRedis.from_url(settings.redis_url)
    lock = redis.lock(_COHORT_LOCK_NAME, timeout=_COHORT_LOCK_TIMEOUT_SECONDS, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("refresh_buyout_cohorts skipped: another pass holds the lock.")
        redis.close()
        return {"skipped_already_running": 1}

    async def _run() -> dict[str, int]:
        async with AsyncSessionLocal() as session:
            bundles = await load_workspace_token_bundles(session)
        total = 0
        failures: list[str] = []
        for bundle in bundles:
            try:
                total += await _refresh_workspace_cohorts(bundle, days)
            except Exception as exc:  # isolate workspaces from each other
                logger.warning("Cohort refresh failed for '%s': %s", bundle.name, exc)
                failures.append(bundle.name)
        # One workspace with a revoked token must not fail the pass, but every
        # workspace failing is a systemic outage and has to be reported as one —
        # otherwise the cohorts stop maturing behind a green task.
        if bundles and len(failures) == len(bundles):
            raise IntegrationError(
                f"Cohort refresh failed for every workspace ({', '.join(failures)}); see logs."
            )
        # Then the days this pass no longer reads: a hole there is permanent
        # unless somebody asks WB again (`funnel_gaps.py`).
        gap_days = 0
        for bundle in bundles:
            try:
                remaining = await heal_funnel_gaps(bundle, today=moscow_today(), cohort_days=days)
            except Exception as exc:  # a repair must not fail the pass it follows
                logger.warning("Funnel gap repair failed for '%s': %s", bundle.name, exc)
                continue
            announce_funnel_gaps(bundle, remaining)
            gap_days += len(remaining)
        FUNNEL_GAP_DAYS.set(gap_days)
        return {"cohort_rows": total, "funnel_gap_days": gap_days}

    try:
        return run_task(_run())
    finally:
        try:
            lock.release()
        except LockError:
            logger.warning("refresh_buyout_cohorts lock already expired at release time.")
        redis.close()
