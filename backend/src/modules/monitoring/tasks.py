"""Celery background tasks for harvesting WildBerries data.

Celery task entrypoints are synchronous, but the entire I/O stack (HTTP + DB) is
async. Each task therefore drives an async coroutine to completion via
``asyncio.run`` and manages its own :class:`AsyncSession` — it cannot use the
FastAPI request-scoped ``get_db`` dependency, so it composes the same
repository/service graph manually.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from redis import Redis as SyncRedis
from redis.exceptions import LockError
from sqlalchemy.exc import OperationalError

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBCardClient,
    WBContentClient,
    WBPricesClient,
)
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBCampaign,
    WBCard,
    WBNormQueryItem,
)
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService

logger = get_logger(__name__)

#: Distributed-lock name preventing overlapping full harvests (the WB
#: advertising surface allows ~1 req/min — two concurrent harvests starve
#: each other into retry exhaustion).
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"

#: Generous ceiling on one harvest run; the lock auto-expires after this so a
#: crashed worker can never wedge the nightly schedule permanently.
_HARVEST_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60

#: Shared retry policy for the harvest tasks: transient WB/DB failures are
#: retried with exponential backoff instead of silently producing a
#: zero-row "success".
_TASK_RETRY_KWARGS: dict[str, object] = {
    "autoretry_for": (IntegrationError, OperationalError),
    "max_retries": 3,
    "retry_backoff": 120,  # 2 min, 4 min, 8 min
    "retry_backoff_max": 900,
    "retry_jitter": True,
}


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


#: WB campaign statuses that can have activity in a recent window: active (9)
#: and paused (11). Completed/declined/deleting campaigns ended before it.
_HARVESTABLE_STATUSES: frozenset[int] = frozenset({9, 11})


def _advertising_harvest_ids(
    campaigns: list[WBCampaign],
    adverts: list[WBAdvertV2] | None,
    nm_ids: list[int],
) -> list[int]:
    """Pick the campaigns to pull fullstats for, scoped to the harvested SKUs.

    Only active/paused campaigns can have recent-window data. When the
    adverts-v2 settings are available, further restrict to campaigns whose
    ``nm_settings`` include one of ``nm_ids`` — so a single-SKU refresh pulls
    only that SKU's campaigns instead of the whole account's. A full harvest
    (``nm_ids`` spanning the catalogue) keeps essentially every campaign, so the
    nightly run is unaffected. Falls back to all active/paused campaigns when
    the settings source failed.

    Args:
        campaigns: Campaign descriptors from ``promotion/count``.
        adverts: Campaign settings from ``adverts-v2`` (``None`` if it failed).
        nm_ids: The SKUs being harvested.

    Returns:
        The campaign ids to request fullstats for.
    """
    active = [c.campaign_id for c in campaigns if c.status in _HARVESTABLE_STATUSES]
    if adverts is None:
        return active
    wanted = set(nm_ids)
    campaigns_for_sku = {
        advert.campaign_id
        for advert in adverts
        if any(setting.nm_id in wanted for setting in advert.nm_settings)
    }
    return [cid for cid in active if cid in campaigns_for_sku]


def _candidate_search_pairs(
    adverts: list[WBAdvertV2] | None,
    nm_ids: list[int],
    harvest_ids: list[int],
) -> list[tuple[int, int]]:
    """Candidate ``(campaign_id, nm_id)`` pairs for the search-zone slice.

    Only campaigns enabled in BOTH display zones (every unified-bid campaign,
    plus dual-placement manual ones) need the normquery slice — a single-zone
    campaign's fullstats already belong wholly to its one zone. Pairs are the
    dual-zone campaigns among the scoped harvest set, crossed with the harvested
    SKUs they advertise (from ``nm_settings``).

    Deriving these from campaign SETTINGS (not fullstats results) is what lets
    the normquery call run **concurrently** with fullstats instead of waiting on
    it — the two are the harvest's slowest, formerly-sequential WB round-trips.
    Pairs that turn out not to have delivered simply return empty stats and are
    dropped on ingest, so the persisted result is unchanged.

    Args:
        adverts: Campaign settings from adverts-v2; ``None`` when that source
            failed — no placement flags means no split is possible.
        nm_ids: The SKUs being harvested.
        harvest_ids: The scoped advertising campaign ids (see
            :func:`_advertising_harvest_ids`).

    Returns:
        Sorted, de-duplicated ``(campaign_id, nm_id)`` pairs.
    """
    if adverts is None:
        return []
    wanted = set(nm_ids)
    scoped = set(harvest_ids)
    pairs: set[tuple[int, int]] = set()
    for advert in adverts:
        placements = advert.settings.placements
        if advert.campaign_id not in scoped or not (
            placements.search and placements.recommendations
        ):
            continue
        for setting in advert.nm_settings:
            if setting.nm_id in wanted:
                pairs.add((advert.campaign_id, setting.nm_id))
    return sorted(pairs)


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
        WBPricesClient(settings) as prices_client,
        WBCardClient(settings) as card_client,
    ):
        # Fire the independent WB calls concurrently and RESILIENTLY:
        # ``return_exceptions`` keeps one failing source (e.g. a stale funnel
        # window or a 429) from aborting the whole harvest. Prices (seller) and
        # the storefront card (customer) join the fan-out for the daily price
        # snapshot.
        (
            funnel_res,
            stock_res,
            camp_res,
            adverts_res,
            prices_res,
            card_res,
        ) = await asyncio.gather(
            analytics_client.fetch_sales_funnel(
                nm_ids=nm_ids, date_from=date_from, date_to=date_to
            ),
            analytics_client.fetch_warehouse_stocks(nm_ids=nm_ids),
            advertising_client.list_campaigns(),
            advertising_client.list_adverts(),
            prices_client.fetch_prices(),
            card_client.fetch_customer_prices(nm_ids),
            return_exceptions=True,
        )
        # Partial failure is tolerated (a 429 on one source must not void the
        # others), but ALL sources failing means the harvest did nothing —
        # raising marks the task FAILED and triggers the retry policy instead
        # of recording a deceptive zero-row "success" (e.g. a revoked token).
        if all(
            isinstance(r, BaseException) for r in (funnel_res, stock_res, camp_res, adverts_res)
        ):
            raise IntegrationError(
                f"Every WB source failed for the harvest window {date_from}..{date_to}: "
                f"{funnel_res}; {stock_res}; {camp_res}; {adverts_res}"
            )
        funnel_rows = _unwrap(funnel_res, "sales-funnel") or []
        stock_rows = _unwrap(stock_res, "stocks") or []
        campaigns = _unwrap(camp_res, "campaigns") or []
        adverts = _unwrap(adverts_res, "adverts-v2")
        stocks_succeeded = not isinstance(stock_res, BaseException)
        # ``None`` (source failed) leaves the price snapshot unwritten; a failed
        # card fetch still lets a seller-only snapshot through.
        prices = _unwrap(prices_res, "prices")
        customer_prices = _unwrap(card_res, "card-prices")

        # Advertising fullstats + search-zone (normquery) stats. Both depend
        # only on the campaign list / settings from the gather above (the
        # normquery pairs come from campaign SETTINGS, not fullstats results),
        # so they run CONCURRENTLY — the two slowest WB round-trips no longer
        # queue behind each other.
        #
        # Fullstats is scoped to campaigns that actually advertise the harvested
        # SKUs: a full (all-SKU) harvest keeps every active campaign, but a
        # targeted single-SKU refresh drops the account's other campaigns —
        # turning a ~all-campaigns pull into a handful, the bulk of the latency.
        harvest_ids = _advertising_harvest_ids(campaigns, adverts, nm_ids)
        search_pairs = _candidate_search_pairs(adverts, nm_ids, harvest_ids)

        async def _fetch_fullstats() -> list[WBAdvCampaignStats]:
            if not harvest_ids:
                return []
            return await advertising_client.fetch_full_stats(
                campaign_ids=harvest_ids, date_from=date_from, date_to=date_to
            )

        async def _fetch_search() -> list[WBNormQueryItem] | None:
            if not search_pairs:
                return None
            return await advertising_client.fetch_search_zone_stats(
                pairs=search_pairs, date_from=date_from, date_to=date_to
            )

        adv_res, search_res = await asyncio.gather(
            _fetch_fullstats(), _fetch_search(), return_exceptions=True
        )
        advertising_stats = _unwrap(adv_res, "advertising") or []
        # ``None`` (source failed OR no pairs) leaves the search facts untouched;
        # a real list drives the ingest + stale-row sweep.
        search_stats = _unwrap(search_res, "search-zone")

    async with AsyncSessionLocal() as session:
        service = IngestionService(
            funnel_repo=FunnelRepository(session),
            advertising_repo=AdvertisingRepository(session),
            stock_repo=StockRepository(session),
            campaign_repo=CampaignRepository(session),
            product_card_repo=ProductCardRepository(session),
            product_size_repo=ProductSizeRepository(session),
            advertising_search_repo=AdvertisingSearchRepository(session),
            price_repo=PriceRepository(session),
        )
        await service.ingest_campaigns(campaigns, adverts)
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
        #
        # The stock sweep (absence-means-zero) only runs when the stocks source
        # actually SUCCEEDED — sweeping on a failed fetch would delete the
        # day's valid rows and re-insert nothing.
        result = await service.ingest_all(
            funnel=funnel_rows,
            advertising=advertising_stats,
            stocks=stock_rows,
            snapshot_date=moscow_today(),
            harvested_nm_ids=nm_ids if stocks_succeeded else [],
            advertising_window=(date_from, date_to),
            search_stats=search_stats,
            search_requested_campaign_ids=sorted({cid for cid, _ in search_pairs}),
            prices=prices,
            customer_prices=customer_prices,
            price_nm_ids=nm_ids,
        )
        # Fresh WB data supersedes any manual matrix edits for these SKUs — the
        # product rule is that any refresh (nightly or a manual «Обновить»)
        # clears saved overrides. Run in the same transaction as the ingest.
        cleared = await MatrixOverrideRepository(session).delete_for_skus(nm_ids)
        if cleared:
            logger.info("Cleared %d manual matrix overrides after refresh.", cleared)
        await session.commit()

    return {
        "funnel_rows": result.funnel_rows,
        "advertising_rows": result.advertising_rows,
        "search_zone_rows": result.search_zone_rows,
        "stock_rows": result.stock_rows,
        "price_rows": result.price_rows,
        "product_card_rows": card_count,
        "product_size_rows": size_count,
    }


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_sku_window",
    bind=False,
    **_TASK_RETRY_KWARGS,
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
    end = date.fromisoformat(date_to) if date_to else moscow_today() - timedelta(days=1)
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

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    return await _harvest_sku_window(nm_ids=nm_ids, date_from=start, date_to=end, cards=cards)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_all",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def harvest_all(days: int = 7) -> dict[str, int]:
    """Scheduled entrypoint: harvest ALL account SKUs over the last ``days``.

    Discovers the full SKU list from the content API, then harvests funnel +
    stock for every SKU and advertising for all active/paused campaigns across a
    rolling window ending yesterday. This is the task Celery Beat runs nightly.

    Guarded by a Redis lock so a manual run cannot overlap the nightly one —
    two concurrent harvests would compete for WB's ~1 req/min advertising
    budget and starve each other into retry exhaustion.

    Args:
        days: Rolling window length (default 7 — the funnel-history cap).

    Returns:
        A mapping of persisted row counts per metric family, or
        ``{"skipped_already_running": 1}`` when another harvest holds the lock.
    """
    # A dedicated SYNC client: the shared async client would bind its
    # connection pool to this task's short-lived event loop (the same
    # cross-loop pitfall the engine.dispose() below works around).
    redis = SyncRedis.from_url(settings.redis_url)
    lock = redis.lock(_HARVEST_LOCK_NAME, timeout=_HARVEST_LOCK_TIMEOUT_SECONDS, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("harvest_all skipped: another harvest already holds the lock.")
        redis.close()
        return {"skipped_already_running": 1}

    logger.info("Nightly harvest_all starting (last %d days).", days)

    async def _run() -> dict[str, int]:
        try:
            return await _discover_and_harvest(days)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    finally:
        try:
            lock.release()
        except LockError:
            # The lock timed out and was re-acquired elsewhere; nothing to do.
            logger.warning("harvest_all lock already expired at release time.")
        redis.close()
