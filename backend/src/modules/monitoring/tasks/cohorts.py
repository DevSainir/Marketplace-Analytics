"""The buyout-cohort refresh: re-read maturing order-date cohorts, day by day."""

from __future__ import annotations

from datetime import timedelta

from redis import Redis as SyncRedis
from redis.exceptions import LockError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal, run_task
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBAnalyticsClient
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
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
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)

#: How far back the cohort pass re-reads order-date cohorts. «Процент выкупа»
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


async def _refresh_workspace_cohorts(tokens: WorkspaceTokenBundle, days: int) -> int:
    """Re-read one workspace's maturing buyout/cancel cohorts, day by day.

    The aggregate endpoint takes a period, not a series, so one call per cohort
    day is unavoidable — but each call answers for the seller's WHOLE catalogue
    (WB ignores the ``nmIDs`` filter), so this is ``days`` requests per
    workspace regardless of SKU count, not ``days x SKUs``.

    Days are fetched sequentially and failures are isolated per day: this
    surface is rate-limited, and a 429 on one cohort must not cost the others
    (the client already honours ``Retry-After`` internally).

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: How many days back from yesterday to re-read.

    Returns:
        The number of cohort days refreshed across the window.
    """
    if not tokens.analytics:
        logger.warning("Workspace '%s' has no analytics token; skipping cohorts.", tokens.name)
        return 0

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    refreshed = 0
    async with WBAnalyticsClient(settings, token=tokens.analytics) as analytics_client:
        for offset in range(days):
            day = end - timedelta(days=offset)
            try:
                rows = await analytics_client.fetch_funnel_cohort_day(day=day)
            except Exception as exc:  # isolate one cohort day from the rest
                logger.warning("Cohort refresh failed for %s: %s", day, exc)
                continue
            async with AsyncSessionLocal() as session:
                service = _cohort_ingestion_service(session)
                refreshed += await service.ingest_funnel_cohorts(day, rows)
                await session.commit()
    logger.info(
        "Refreshed %d cohort days for workspace '%s' (%d-day window).",
        refreshed,
        tokens.name,
        days,
    )
    return refreshed


def _cohort_ingestion_service(session: AsyncSession) -> IngestionService:
    """Build an IngestionService for the cohort pass.

    Only ``funnel_repo`` is exercised, but the service wires its full
    repository graph — the others are constructed and left unused.
    """
    return IngestionService(
        funnel_repo=FunnelRepository(session),
        advertising_repo=AdvertisingRepository(session),
        stock_repo=StockRepository(session),
        campaign_repo=CampaignRepository(session),
        product_card_repo=ProductCardRepository(session),
        product_size_repo=ProductSizeRepository(session),
        advertising_search_repo=AdvertisingSearchRepository(session),
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
    «Обновить» refresh that ``harvest_sku_window`` serves.

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
        for bundle in bundles:
            try:
                total += await _refresh_workspace_cohorts(bundle, days)
            except Exception as exc:  # isolate workspaces from each other
                logger.warning("Cohort refresh failed for '%s': %s", bundle.name, exc)
        return {"cohort_rows": total}

    try:
        return run_task(_run())
    finally:
        try:
            lock.release()
        except LockError:
            logger.warning("refresh_buyout_cohorts lock already expired at release time.")
        redis.close()
