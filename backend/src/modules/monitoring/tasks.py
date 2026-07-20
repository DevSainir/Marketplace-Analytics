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
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today, operating_today
from src.integrations.wildberries import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBCardClient,
    WBContentClient,
    WBPricesClient,
    WBStatisticsClient,
)
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBCampaign,
    WBCard,
    WBNormQueryItem,
    WBSaleRecord,
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
    SaleRepository,
    SkuDayCommentRepository,
    StockRepository,
)
from src.modules.monitoring.services import IngestionService
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)

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

    Every campaign with the SEARCH placement needs the normquery slice:

    * dual-zone campaigns (every unified-bid one, plus dual-placement manual
      ones) — the slice splits «Поиск» from «Полки»;
    * search-only manual campaigns — WB «поисковые» campaigns also deliver in
      the CATALOG zone (verified live: fullstats runs ~10-13% above the
      normquery sum day after day), so the slice splits «Поиск» from
      «Каталог».

    A shelves-only campaign's fullstats already belong wholly to its one zone.
    Pairs are the search-placement campaigns among the scoped harvest set,
    crossed with the harvested SKUs they advertise (from ``nm_settings``).

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
        if advert.campaign_id not in scoped or not placements.search:
            continue
        for setting in advert.nm_settings:
            if setting.nm_id in wanted:
                pairs.add((advert.campaign_id, setting.nm_id))
    return sorted(pairs)


async def _harvest_sku_window(
    *,
    tokens: WorkspaceTokenBundle,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    cards: list[WBCard] | None = None,
    include_sales: bool = True,
) -> dict[str, int]:
    """Fetch, flatten, and persist a full harvest for one workspace's SKUs.

    Opens a dedicated async DB session and transaction, calls the WB clients
    resiliently, delegates flattening/persistence to :class:`IngestionService`,
    and commits atomically. Advertising is pulled for the active/paused
    campaigns that advertise ``nm_ids`` (see :func:`_advertising_harvest_ids`),
    so a SKU's detail view shows every campaign that spent on it during the
    window, without dragging in the rest of the account's.

    Args:
        tokens: The owning workspace's decrypted WB credentials. A surface
            with an empty token simply fails auth and is skipped like any
            other failed source (partial harvests are already tolerated).
        nm_ids: SKU identifiers to harvest funnel + stock for.
        date_from: Inclusive window start (Moscow time).
        date_to: Inclusive window end (Moscow time).
        cards: Optional Content API cards to refresh the catalogue dimensions
            (vendor codes + size labels) in the same transaction. Passed by the
            discover flow, which already fetched them to derive ``nm_ids``.
        include_sales: Whether to pull the sale/return feed. It is the one
            source WB serves ONLY account-wide (``supplier/sales`` takes a
            ``dateFrom`` and no SKU filter), so a single-SKU refresh would
            re-fetch and re-ingest every SKU's sales to update one — on the
            harshest limiter WB has. The nightly harvest keeps it ``True``;
            the manual «Обновить» passes ``False``. See
            :func:`harvest_sku_window`.

    Returns:
        A mapping of persisted row counts per metric family (plus catalogue
        counts when ``cards`` is supplied).
    """
    async with (
        WBAnalyticsClient(settings, token=tokens.analytics) as analytics_client,
        WBAdvertisingClient(settings, token=tokens.advertising) as advertising_client,
        WBPricesClient(settings, token=tokens.prices) as prices_client,
        WBCardClient(settings) as card_client,
        WBStatisticsClient(settings, token=tokens.statistics) as statistics_client,
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

        # The statistics sales feed rides this second wave: sale-date
        # buyout/return records, incremental by lastChangeDate — the window
        # start suffices, since a late return of an old sale carries a fresh
        # change stamp. Skipped entirely when the caller did not ask for it
        # (a single-SKU refresh): the feed is account-wide, so it cannot be
        # narrowed to this SKU, and it is rate-limited hard enough that
        # fetching it dominates the refresh.
        async def _fetch_sales() -> list[WBSaleRecord] | None:
            if not include_sales:
                return None
            return await statistics_client.fetch_sales(changed_since=date_from)

        adv_res, search_res, sales_res = await asyncio.gather(
            _fetch_fullstats(),
            _fetch_search(),
            _fetch_sales(),
            return_exceptions=True,
        )
        advertising_stats = _unwrap(adv_res, "advertising") or []
        # ``None`` (source failed OR no pairs) leaves the search facts untouched;
        # a real list drives the ingest + stale-row sweep.
        search_stats = _unwrap(search_res, "search-zone")
        # ``None`` (source failed) leaves the sale/return records untouched.
        sales = _unwrap(sales_res, "sales")

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
            sale_repo=SaleRepository(session),
        )
        await service.ingest_campaigns(campaigns, adverts)
        # Refresh the product catalogue (vendor codes + size labels) so the
        # label-less funnel/stock facts can be decorated with human identifiers.
        # Cards are stamped with the harvesting workspace — the SKU -> workspace
        # registry every tenant-scoped read is built on.
        card_count = size_count = 0
        if cards is not None:
            catalog = await service.ingest_catalog(cards, workspace_id=tokens.workspace_id)
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
            sales=sales,
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
        "sales_rows": result.sales_rows,
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

    Harvests funnel + stock for ``nm_ids`` and advertising for the campaigns
    that advertise them, using the credentials of the workspace that **owns**
    the SKUs (resolved via the ``product_card`` registry). Args are
    JSON-serializable (dates as ISO strings) to satisfy Celery's JSON task
    serializer.

    This is the interactive «Обновить» path, so it fetches ONLY what is scoped
    to ``nm_ids``. The sale/return feed is therefore skipped: WB serves it
    account-wide only, so refreshing one SKU would re-pull every SKU's sales
    across the harshest limiter WB exposes — observed live as a 39-second 429
    backoff that made a ~2-second refresh take 45-70 seconds. Sale-date facts
    («Выкупы, ₽», «Процент выкупа») are account-wide by nature and stay on the
    nightly harvest.

    Args:
        nm_ids: SKU identifiers to harvest funnel + stock for. All must belong
            to one workspace (in practice the refresh endpoint passes one SKU).
        date_from: Optional ISO start date; defaults to a 7-day window (the WB
            funnel-history endpoint rejects windows longer than 7 days).
        date_to: Optional ISO end date; defaults to Moscow *yesterday* (WB does
            not serve current-day statistics).

    Returns:
        A mapping of persisted row counts per metric family (``sales_rows`` is
        always 0 — the feed is not part of a scoped refresh).

    Raises:
        IntegrationError: If the SKUs are not registered to any workspace, or
            the workspace no longer exists (no credentials to harvest with).
    """
    # WB rejects the current date, so the default window ends yesterday; the
    # funnel-history endpoint caps the window at 7 inclusive days.
    end = date.fromisoformat(date_to) if date_to else moscow_today() - timedelta(days=1)
    start = date.fromisoformat(date_from) if date_from else end - timedelta(days=6)
    logger.info("Harvesting SKUs %s for %s..%s", nm_ids, start, end)

    async def _run() -> dict[str, int]:
        try:
            async with AsyncSessionLocal() as session:
                workspace_id = await ProductCardRepository(session).get_workspace_of_sku(nm_ids[0])
                if workspace_id is None:
                    raise IntegrationError(
                        f"SKU {nm_ids[0]} is not registered to any workspace; "
                        "cannot pick WB credentials for the refresh."
                    )
                tokens = await load_workspace_token_bundle(session, workspace_id)
            if tokens is None:
                raise IntegrationError(
                    f"Workspace {workspace_id} no longer exists; refresh aborted."
                )
            return await _harvest_sku_window(
                tokens=tokens,
                nm_ids=nm_ids,
                date_from=start,
                date_to=end,
                include_sales=False,
            )
        finally:
            # Each Celery task runs its own asyncio.run (a fresh event loop).
            # Dispose the shared engine's pool so its connections aren't left
            # bound to this now-closed loop — otherwise the NEXT task in the same
            # worker process fails with "Future attached to a different loop".
            await engine.dispose()

    return asyncio.run(_run())


async def _discover_and_harvest_workspace(
    tokens: WorkspaceTokenBundle, days: int
) -> dict[str, int]:
    """Discover one workspace's SKUs and harvest a rolling ``days``-day window.

    Discovery runs with the workspace's own Analytics token against the
    Content API, so the resulting cards — and everything harvested for them —
    are provably that workspace's SKUs.

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: Length of the inclusive window ending yesterday (Moscow time).

    Returns:
        A mapping of persisted row counts per metric family.

    Raises:
        IntegrationError: If the workspace has no analytics token (discovery
            is impossible without it) or discovery itself fails.
    """
    if not tokens.content:
        raise IntegrationError(
            f"Workspace '{tokens.name}' has no content/analytics token; cannot discover its SKUs."
        )
    async with WBContentClient(settings, token=tokens.content) as content:
        cards = await content.fetch_all_cards()
    nm_ids = [card.nm_id for card in cards]
    logger.info(
        "Discovered %d SKUs from the content API for workspace '%s'.",
        len(nm_ids),
        tokens.name,
    )
    if not nm_ids:
        return {}

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    return await _harvest_sku_window(
        tokens=tokens, nm_ids=nm_ids, date_from=start, date_to=end, cards=cards
    )


async def _discover_and_harvest(days: int) -> dict[str, int]:
    """Harvest every workspace with stored WB tokens, sequentially.

    Sequential (not gathered) on purpose: WB rate-limits per seller account,
    but the process shares one event loop, DB pool, and card-proxy budget —
    and a failed workspace must not poison the others' harvests. Failures are
    logged per workspace and skipped; the run fails only when *every*
    workspace failed (so a single revoked token cannot mask a systemic
    outage into a "success").

    Args:
        days: Length of the inclusive window ending yesterday (Moscow time).

    Returns:
        A mapping of persisted row counts per metric family, summed across
        workspaces, plus ``workspaces_harvested`` / ``workspaces_failed``.

    Raises:
        IntegrationError: When workspaces exist but every one failed.
    """
    async with AsyncSessionLocal() as session:
        bundles = await load_workspace_token_bundles(session)
    if not bundles:
        logger.warning("No workspaces configured; nothing to harvest.")
        return {"workspaces_harvested": 0, "workspaces_failed": 0}

    totals: dict[str, int] = {"workspaces_harvested": 0, "workspaces_failed": 0}
    failures: list[str] = []
    for bundle in bundles:
        try:
            result = await _discover_and_harvest_workspace(bundle, days)
        except Exception as exc:  # isolate workspaces from each other
            logger.warning("Harvest failed for workspace '%s': %s", bundle.name, exc)
            failures.append(bundle.name)
            totals["workspaces_failed"] += 1
            continue
        totals["workspaces_harvested"] += 1
        for key, value in result.items():
            totals[key] = totals.get(key, 0) + value

    if totals["workspaces_harvested"] == 0:
        raise IntegrationError(f"Every workspace harvest failed ({', '.join(failures)}); see logs.")
    return totals


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_all",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def harvest_all(days: int = 7) -> dict[str, int]:
    """Scheduled entrypoint: harvest every workspace's SKUs over the last ``days``.

    Iterates all workspaces with WB tokens stored (encrypted) in the database;
    for each, discovers its full SKU list from the content API with its own
    credentials, then harvests funnel + stock for every SKU and advertising
    for all active/paused campaigns across a rolling window ending yesterday.
    This is the task Celery Beat runs nightly.

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
        try:
            async with AsyncSessionLocal() as session:
                bundles = await load_workspace_token_bundles(session)
            total = 0
            for bundle in bundles:
                try:
                    total += await _refresh_workspace_cohorts(bundle, days)
                except Exception as exc:  # isolate workspaces from each other
                    logger.warning("Cohort refresh failed for '%s': %s", bundle.name, exc)
            return {"cohort_rows": total}
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    finally:
        try:
            lock.release()
        except LockError:
            logger.warning("refresh_buyout_cohorts lock already expired at release time.")
        redis.close()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.carry_day_headers",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def carry_day_headers() -> dict[str, int]:
    """Scheduled entrypoint: carry the previous day's note headers onto the new one.

    The matrix's notes row has two fields per day: a free-text comment, which
    is purely per-day, and a header — a running title that should continue onto
    each new day without being retyped. That continuation happens HERE, once,
    when the day rolls over, and it writes a real row for the new day. Making
    the carry a stored fact rather than a live inheritance is what lets a
    manager then edit or clear any single day's header without disturbing the
    days around it.

    The source is STRICTLY the previous day — never the last day that happened
    to have a title. A blank header yesterday means the new day starts blank,
    even when an older day still carries one.

    Dated on the TEAM's clock (:func:`operating_today`), not WB's: the day the
    managers see turn over at 00:00 Bishkek is the one that should receive the
    title, and the beat fires at exactly that instant (21:00 MSK).

    A day that already has a header is never overwritten, so re-running the
    task is a no-op.

    Returns:
        ``{"headers_carried": n}``.
    """

    async def _run() -> dict[str, int]:
        try:
            today = operating_today()
            async with AsyncSessionLocal() as session:
                repo = SkuDayCommentRepository(session)
                carried = await repo.carry_headers_to_day(
                    source_day=today - timedelta(days=1), target_day=today
                )
                await session.commit()
            logger.info("Carried %d note header(s) onto %s.", carried, today.isoformat())
            return {"headers_carried": carried}
        finally:
            await engine.dispose()

    return asyncio.run(_run())
