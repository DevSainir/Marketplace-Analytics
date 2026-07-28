"""The SKU-window harvest: fetch WB sources concurrently, ingest atomically.

Owns the harvest core (:func:`_harvest_sku_window`) shared by the interactive
«Обновить» task below and the nightly discovery flow
(:mod:`~src.modules.monitoring.tasks.discovery`).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal, run_task
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import (
    WBAdvertisingClient,
    WBAnalyticsClient,
    WBCardClient,
    WBPricesClient,
    WBStatisticsClient,
)
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
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
    StockRepository,
)
from src.modules.monitoring.services import IngestionService
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS, _unwrap
from src.modules.monitoring.tasks.planning import (
    _advertising_harvest_ids,
    _candidate_search_pairs,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
)

logger = get_logger(__name__)


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
        async with AsyncSessionLocal() as session:
            workspace_id = await ProductCardRepository(session).get_workspace_of_sku(nm_ids[0])
            if workspace_id is None:
                raise IntegrationError(
                    f"SKU {nm_ids[0]} is not registered to any workspace; "
                    "cannot pick WB credentials for the refresh."
                )
            tokens = await load_workspace_token_bundle(session, workspace_id)
        if tokens is None:
            raise IntegrationError(f"Workspace {workspace_id} no longer exists; refresh aborted.")
        return await _harvest_sku_window(
            tokens=tokens,
            nm_ids=nm_ids,
            date_from=start,
            date_to=end,
            include_sales=False,
        )

    return run_task(_run())
