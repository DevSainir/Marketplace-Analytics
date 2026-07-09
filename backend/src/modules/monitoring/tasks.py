"""Celery background tasks for harvesting WildBerries data.

Celery task entrypoints are synchronous, but the entire I/O stack (HTTP + DB) is
async. Each task therefore drives an async coroutine to completion via
``asyncio.run`` and manages its own :class:`AsyncSession` — it cannot use the
FastAPI request-scoped ``get_db`` dependency, so it composes the same
repository/service graph manually.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBContentClient,
)
from src.integrations.wildberries.schemas import WBAdvCampaignStats, WBCard
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    CampaignRepository,
    FunnelRepository,
    ProductCardRepository,
    ProductSizeRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService

logger = get_logger(__name__)

#: WB operates strictly in Moscow Time (UTC+3).
_MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def _unwrap[T](result: T | BaseException | None, label: str) -> T | None:
    """Return a gathered result, or ``None`` if that WB source raised.

    Used with ``asyncio.gather(return_exceptions=True)`` so one failed source
    is logged and skipped instead of aborting the whole harvest.

    Args:
        result: The value the source produced, an exception it raised, or
            ``None`` when the source was not requested.
        label: Human-readable source name for the log line.

    Returns:
        The successful value, or ``None`` on failure/absence.
    """
    if isinstance(result, BaseException):
        logger.warning("Harvest source '%s' failed and was skipped: %s", label, result)
        return None
    return result


def _moscow_today() -> date:
    """Return the current calendar date in Moscow time (UTC+3)."""
    return datetime.now(tz=_MOSCOW_TZ).date()


#: WB campaign statuses that can have activity in a recent window: active (9)
#: and paused (11). Completed/declined/deleting campaigns ended before it.
_HARVESTABLE_STATUSES: frozenset[int] = frozenset({9, 11})


async def _harvest_sku_window(
    *,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    cards: list[WBCard] | None = None,
) -> dict[str, int]:
    """Fetch, flatten, and persist a full harvest for the given SKUs.

    Opens a dedicated async DB session and transaction, calls the WB clients
    resiliently, delegates flattening/persistence to :class:`IngestionService`,
    and commits atomically. Advertising is pulled for **all active + paused
    campaigns** (not a single id), so a SKU's detail view shows every campaign
    that spent on it during the window.

    Args:
        nm_ids: SKU identifiers to harvest funnel + stock for.
        date_from: Inclusive window start (Moscow time).
        date_to: Inclusive window end (Moscow time).
        cards: Optional Content API cards to refresh the catalogue dimensions
            (vendor codes + size labels) in the same transaction. Passed by the
            discover flow, which already fetched them to derive ``nm_ids``.

    Returns:
        A mapping of persisted row counts per metric family (plus catalogue
        counts when ``cards`` is supplied).
    """
    async with (
        WBAnalyticsClient(settings) as analytics_client,
        WBAdvertisingClient(settings) as advertising_client,
    ):
        # Fire the independent WB calls concurrently and RESILIENTLY:
        # ``return_exceptions`` keeps one failing source (e.g. a stale funnel
        # window or a 429) from aborting the whole harvest.
        funnel_res, stock_res, camp_res = await asyncio.gather(
            analytics_client.fetch_sales_funnel(
                nm_ids=nm_ids, date_from=date_from, date_to=date_to
            ),
            analytics_client.fetch_warehouse_stocks(nm_ids=nm_ids),
            advertising_client.list_campaigns(),
            return_exceptions=True,
        )
        funnel_rows = _unwrap(funnel_res, "sales-funnel") or []
        stock_rows = _unwrap(stock_res, "stocks") or []
        campaigns = _unwrap(camp_res, "campaigns") or []

        # Advertising fullstats for every campaign that could have window data.
        # Depends on the campaign list, so it runs after the gather above.
        harvest_ids = [c.campaign_id for c in campaigns if c.status in _HARVESTABLE_STATUSES]
        advertising_stats: list[WBAdvCampaignStats] = []
        if harvest_ids:
            try:
                advertising_stats = await advertising_client.fetch_full_stats(
                    campaign_ids=harvest_ids, date_from=date_from, date_to=date_to
                )
            except IntegrationError as exc:
                logger.warning("Harvest source 'advertising' failed and was skipped: %s", exc)

    async with AsyncSessionLocal() as session:
        service = IngestionService(
            funnel_repo=FunnelRepository(session),
            advertising_repo=AdvertisingRepository(session),
            stock_repo=StockRepository(session),
            campaign_repo=CampaignRepository(session),
            product_card_repo=ProductCardRepository(session),
            product_size_repo=ProductSizeRepository(session),
        )
        await service.ingest_campaigns(campaigns)
        # Refresh the product catalogue (vendor codes + size labels) so the
        # label-less funnel/stock facts can be decorated with human identifiers.
        card_count = size_count = 0
        if cards is not None:
            catalog = await service.ingest_catalog(cards)
            card_count = catalog.product_card_rows
            size_count = catalog.product_size_rows
        # Stock is a LIVE snapshot (WB exposes no stock history), so it is dated
        # by its capture day — not the funnel/advertising window end, which lags
        # a day because WB has no current-day funnel/ad data. Running the harvest
        # daily is what accumulates a per-day stock series over time.
        result = await service.ingest_all(
            funnel=funnel_rows,
            advertising=advertising_stats,
            stocks=stock_rows,
            snapshot_date=_moscow_today(),
        )
        await session.commit()

    return {
        "funnel_rows": result.funnel_rows,
        "advertising_rows": result.advertising_rows,
        "stock_rows": result.stock_rows,
        "product_card_rows": card_count,
        "product_size_rows": size_count,
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_sku_window", bind=False
)
def harvest_sku_window(
    nm_ids: list[int],
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, int]:
    """Celery entrypoint: harvest and persist WB stats for a SKU window.

    Harvests funnel + stock for ``nm_ids`` and advertising for all active/paused
    campaigns. Args are JSON-serializable (dates as ISO strings) to satisfy
    Celery's JSON task serializer.

    Args:
        nm_ids: SKU identifiers to harvest funnel + stock for.
        date_from: Optional ISO start date; defaults to a 7-day window (the WB
            funnel-history endpoint rejects windows longer than 7 days).
        date_to: Optional ISO end date; defaults to Moscow *yesterday* (WB does
            not serve current-day statistics).

    Returns:
        A mapping of persisted row counts per metric family.
    """
    # WB rejects the current date, so the default window ends yesterday; the
    # funnel-history endpoint caps the window at 7 inclusive days.
    end = date.fromisoformat(date_to) if date_to else _moscow_today() - timedelta(days=1)
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=6)
    logger.info("Harvesting SKUs %s for %s..%s", nm_ids, start, end)

    async def _run() -> dict[str, int]:
        try:
            return await _harvest_sku_window(nm_ids=nm_ids, date_from=start, date_to=end)
        finally:
            # Each Celery task runs its own asyncio.run (a fresh event loop).
            # Dispose the shared engine's pool so its connections aren't left
            # bound to this now-closed loop — otherwise the NEXT task in the same
            # worker process fails with "Future attached to a different loop".
            await engine.dispose()

    return asyncio.run(_run())


async def _discover_and_harvest(days: int) -> dict[str, int]:
    """Discover every account SKU and harvest a rolling ``days``-day window.

    Args:
        days: Length of the inclusive window ending yesterday (Moscow time).

    Returns:
        A mapping of persisted row counts per metric family.
    """
    async with WBContentClient(settings) as content:
        cards = await content.fetch_all_cards()
    nm_ids = [card.nm_id for card in cards]
    logger.info("Discovered %d SKUs from the content API", len(nm_ids))

    end = _moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    return await _harvest_sku_window(nm_ids=nm_ids, date_from=start, date_to=end, cards=cards)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_all", bind=False
)
def harvest_all(days: int = 7) -> dict[str, int]:
    """Scheduled entrypoint: harvest ALL account SKUs over the last ``days``.

    Discovers the full SKU list from the content API, then harvests funnel +
    stock for every SKU and advertising for all active/paused campaigns across a
    rolling window ending yesterday. This is the task Celery Beat runs nightly.

    Args:
        days: Rolling window length (default 7 — the funnel-history cap).

    Returns:
        A mapping of persisted row counts per metric family.
    """
    logger.info("Nightly harvest_all starting (last %d days).", days)

    async def _run() -> dict[str, int]:
        try:
            return await _discover_and_harvest(days)
        finally:
            await engine.dispose()

    return asyncio.run(_run())
