"""The SKU-window harvest: fetch WB sources concurrently, ingest atomically.

Owns the harvest core (:func:`_harvest_sku_window`) shared by the interactive
«Обновить» task below and the nightly discovery flow
(:mod:`~src.modules.monitoring.tasks.discovery`).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.timeutils import moscow_today
from src.integrations.wildberries import (
    WBAnalyticsClient,
    build_advertising_client,
    build_analytics_client,
    build_card_client,
    build_prices_client,
    build_statistics_client,
)
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvWriteOff,
    WBCard,
    WBFunnelHistoryRow,
    WBNormQueryItem,
    WBOrderPrice,
    WBSaleRecord,
    WBStockRow,
)
from src.modules.monitoring.repos import (
    AdvertisingClusterRepository,
    AdvertisingRepository,
    AdvertisingSearchRepository,
    AdvertisingWriteOffRepository,
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
from src.modules.monitoring.tasks.common import _unwrap
from src.modules.monitoring.tasks.fbs import fetch_fbs_stock_rows, known_warehouse_labels
from src.modules.monitoring.tasks.planning import (
    _advertising_harvest_ids,
    _candidate_search_pairs,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class HarvestOutcome:
    """What one harvest actually managed to persist, and what WB withheld.

    ``failed_sources`` exists because a harvest is deliberately tolerant of a
    partial WB outage — but "0 funnel rows because WB stalled the request" and
    "0 funnel rows because the SKU had no traffic" are indistinguishable from
    the counts alone. The 2026-07-30 incident hid behind exactly that: tasks
    reported SUCCESS with ``funnel_rows: 0`` while «Обновить» users watched
    unchanged numbers and concluded the button did nothing.
    """

    counts: dict[str, int]
    failed_sources: tuple[str, ...] = ()


async def _fetch_analytics_in_turn(
    client: WBAnalyticsClient,
    *,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
) -> tuple[list[WBFunnelHistoryRow] | BaseException, list[WBStockRow] | BaseException]:
    """Fetch the funnel, then the stocks — never both at once.

    WB meters the analytics surface per endpoint with a bucket only three tokens
    deep, and it does not answer an overrun politely: measured live on
    2026-07-30 it returns HTTP 500, or holds the socket until the client's
    30-second read timeout. Issuing this pair inside one ``asyncio.gather``
    therefore guaranteed that a contended refresh burnt both its retries on
    stalls — «Обновить» took 145-200s and persisted zero funnel rows.

    Awaiting them in turn lets the client's rate gate space them, and keeps a
    failure of one from cancelling the other: each is captured and returned so
    the caller keeps its existing partial-harvest semantics.

    Args:
        client: The workspace's analytics client (holds the rate gate).
        nm_ids: SKUs to fetch both sources for.
        date_from: Inclusive window start (funnel only; stocks are live).
        date_to: Inclusive window end.

    Returns:
        ``(funnel, stocks)``, each either the rows or the exception raised.
    """
    funnel: list[WBFunnelHistoryRow] | BaseException
    stocks: list[WBStockRow] | BaseException
    try:
        funnel = await client.fetch_sales_funnel(
            nm_ids=nm_ids, date_from=date_from, date_to=date_to
        )
    except Exception as exc:
        funnel = exc
    try:
        stocks = await client.fetch_warehouse_stocks(nm_ids=nm_ids)
    except Exception as exc:
        stocks = exc
    return funnel, stocks


async def _harvest_sku_window(
    *,
    tokens: WorkspaceTokenBundle,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    cards: list[WBCard] | None = None,
    include_sales: bool = True,
) -> HarvestOutcome:
    """Fetch, flatten, and persist a full harvest for one workspace's SKUs.

    Opens a dedicated async DB session and transaction, calls the WB clients
    resiliently, delegates flattening/persistence to :class:`IngestionService`,
    and commits atomically. Advertising is pulled for the campaigns that
    advertise ``nm_ids`` and are still running, plus any that already delivered
    inside the window (see :func:`_advertising_harvest_ids`), so a SKU's detail
    view shows every campaign that spent on it during the window — including
    one completed part-way through it — without dragging in the rest of the
    account's.

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
        include_sales: Whether to pull the ACCOUNT-WIDE feeds — the sale/return
            records and WB's advertising write-off ledger. Neither can be
            narrowed to a SKU (``supplier/sales`` takes a ``dateFrom`` and no
            filter; ``/adv/v1/upd`` names campaigns, not cards), so a single-SKU
            refresh re-fetches the whole account to update one card.

            **Every caller passes ``True`` today**, and has since 0c0a752
            (2026-09-07) routed both the nightly pass and the interactive
            «Обновить» through
            :func:`~src.modules.monitoring.tasks.full_refresh.refresh_workspace_data`,
            which hard-codes it. The cost was accepted there deliberately: the
            alternative was a refresh that returned green while «Выкупы, ₽»
            stood still. This docstring claimed the interactive path passed
            ``False`` until 2026-09-15 — it had been wrong for a week.

            The parameter survives as a tripwire rather than as a choice:
            ``tests/unit/monitoring/test_full_refresh_composition.py`` asserts
            it is ``True``, so flipping it back cannot happen quietly.

    Returns:
        The persisted row counts per metric family (plus catalogue counts when
        ``cards`` is supplied), alongside the labels of any WB source that
        failed — a harvest that wrote nothing because WB withheld the funnel is
        not the same event as one that found nothing, and the caller must be
        able to tell the two apart.
    """
    # Each SKU's catalogued size ids, for the synthetic stock client — a real
    # stock response carries its own sizes and the real client discards this
    # (see :func:`build_analytics_client`). Read unconditionally rather than
    # behind the fake-harvest flag: the point of the factory seam is that this
    # body is byte-identical in both environments, and one indexed lookup is
    # nothing beside the WB round-trips below. Cards, when the discover flow
    # already fetched them, additionally cover SKUs the catalogue has not been
    # told about yet — their sizes land later in this same transaction.
    async with AsyncSessionLocal() as session:
        size_ids_by_nm = await ProductSizeRepository(session).get_chrt_ids_by_nm_ids(nm_ids)
        # Campaigns that already delivered inside this window, so the fullstats
        # scope can include the ones WB has since stopped calling active — the
        # day a campaign ENDS on is only ever collectable by the pass that
        # still remembers it (see :func:`_advertising_harvest_ids`).
        recent_campaign_ids = await AdvertisingRepository(session).campaign_ids_in_window(
            nm_ids=nm_ids, date_from=date_from, date_to=date_to
        )
    for card in cards or []:
        if card.sizes:
            size_ids_by_nm[card.nm_id] = sorted({size.chrt_id for size in card.sizes})

    async with (
        build_analytics_client(
            settings, token=tokens.analytics, size_ids_by_nm=size_ids_by_nm
        ) as analytics_client,
        build_advertising_client(settings, token=tokens.advertising) as advertising_client,
        build_prices_client(settings, token=tokens.prices, nm_ids=nm_ids) as prices_client,
        build_card_client(settings) as card_client,
        build_statistics_client(settings, token=tokens.statistics) as statistics_client,
    ):
        # Fire the independent WB calls concurrently and RESILIENTLY:
        # ``return_exceptions`` keeps one failing source (e.g. a stale funnel
        # window or a 429) from aborting the whole harvest. Prices (seller) and
        # the storefront card (customer) join the fan-out for the daily price
        # snapshot.
        #
        # The two ANALYTICS calls are the exception — see
        # :func:`_fetch_analytics_in_turn`. Different HOSTS still run
        # concurrently; only that one surface is serialised.
        (
            analytics_res,
            camp_res,
            adverts_res,
            prices_res,
            card_res,
        ) = await asyncio.gather(
            _fetch_analytics_in_turn(
                analytics_client, nm_ids=nm_ids, date_from=date_from, date_to=date_to
            ),
            advertising_client.list_campaigns(),
            advertising_client.list_adverts(),
            prices_client.fetch_prices(),
            card_client.fetch_customer_prices(nm_ids),
            return_exceptions=True,
        )
        if isinstance(analytics_res, BaseException):
            funnel_res: list[WBFunnelHistoryRow] | BaseException = analytics_res
            stock_res: list[WBStockRow] | BaseException = analytics_res
        else:
            funnel_res, stock_res = analytics_res
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
        # The window's already-delivering campaigns join that scope whatever
        # status WB now gives them, which is what keeps a campaign's closing day.
        harvest_ids = _advertising_harvest_ids(campaigns, adverts, nm_ids, recent_campaign_ids)
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

        # The order feed, read ONLY for the price a customer was charged today.
        # No table, no series: these rows become one column of one day's price
        # snapshot and are dropped (see
        # :class:`~src.integrations.wildberries.schemas.statistics.WBOrderPrice`
        # for why this is not the removed «Заказы» feed coming back).
        #
        # Unlike the sales feed above this runs on EVERY path, single-SKU
        # «Обновить» included, because rewriting today's price with SPP is the
        # button's whole point — and it is cheap enough to mean it: the window
        # is today alone rather than the harvest's, and this endpoint's bucket
        # is 10 requests a minute against the sales feed's one.
        async def _fetch_order_prices() -> list[WBOrderPrice] | None:
            return await statistics_client.fetch_order_prices(changed_since=moscow_today())

        # WB's advertising write-off ledger — the only feed that says whether a
        # charge came out of the seller's money («Баланс») or out of WB's bonus
        # pool («Кэшбэк»). Without it every per-SKU DRR, ROI and profit counts
        # WB's bonuses as the seller's spend, because `fullstats` reports the
        # impressions either way funded and a bonus charge never reaches the
        # settlement report (it has no invoice document).
        #
        # Rides the same gate as the sales feed, and for the same reason: it is
        # served ACCOUNT-WIDE with no campaign filter. That gate is open on
        # every path today (see ``include_sales`` above), so a single-SKU
        # «Обновить» re-fetches and rewrites this window's whole ledger to
        # refresh one card. Cheap enough to accept: a 7-day window is ONE
        # request, and the rewrite is idempotent — the ingest sweeps exactly the
        # window it fetched.
        async def _fetch_write_offs() -> list[WBAdvWriteOff] | None:
            if not include_sales:
                return None
            return await advertising_client.fetch_write_offs(date_from=date_from, date_to=date_to)

        # FBS stock rides this wave too: a different WB host and token category
        # from the FBO stock above, so it neither shares nor contends for the
        # analytics rate budget. It returns ordinary stock rows (see
        # :mod:`~src.modules.monitoring.tasks.fbs`), and a workspace with no
        # «Маркетплейс» token simply gets an empty list.
        (
            adv_res,
            search_res,
            sales_res,
            order_price_res,
            write_off_res,
            fbs_res,
        ) = await asyncio.gather(
            _fetch_fullstats(),
            _fetch_search(),
            _fetch_sales(),
            _fetch_order_prices(),
            _fetch_write_offs(),
            fetch_fbs_stock_rows(settings, token=tokens.marketplace, nm_ids=nm_ids, cards=cards),
            return_exceptions=True,
        )
        advertising_stats = _unwrap(adv_res, "advertising") or []
        # ``None`` (source failed OR no pairs) leaves the search facts untouched;
        # a real list drives the ingest + stale-row sweep.
        search_stats = _unwrap(search_res, "search-zone")
        # ``None`` (source failed) leaves the sale/return records untouched.
        sales = _unwrap(sales_res, "sales")
        # ``None`` (source failed) leaves the customer price to the storefront
        # alone — which since 2026-09-22 means leaving it NULL.
        order_prices = _unwrap(order_price_res, "order-prices")
        # ``None`` (source failed OR not requested) leaves the funding ledger
        # untouched — a missed pass must read as «bonuses unknown for this
        # window», never as «this window had no bonuses».
        write_offs = _unwrap(write_off_res, "ad-write-offs")
        # FBS rows join the FBO ones in the same table, each under its own
        # warehouse label. Any FBS warehouse we did not manage to read is spared
        # from the absence-means-zero sweep — the sources fail independently, and
        # sweeping would report the seller's warehouse as emptied rather than
        # unread. A wholesale FBS failure spares every label we know of, since
        # without a read there is nothing to tell us which warehouses exist.
        fbs = _unwrap(fbs_res, "stocks-fbs")
        stock_rows = [*stock_rows, *(fbs.rows if fbs else [])]
        keep_warehouses = (
            await known_warehouse_labels()
            if isinstance(fbs_res, BaseException)
            else (fbs.unread if fbs else ())
        )

        # Which sources WB actually withheld. Reported all the way to the UI so
        # a refresh that changed nothing says why instead of looking inert.
        failed_sources = tuple(
            label
            for label, result in (
                ("sales-funnel", funnel_res),
                ("stocks", stock_res),
                ("campaigns", camp_res),
                ("adverts-v2", adverts_res),
                ("prices", prices_res),
                ("card-prices", card_res),
                ("advertising", adv_res),
                ("search-zone", search_res),
                ("sales", sales_res),
                ("order-prices", order_price_res),
                ("ad-write-offs", write_off_res),
                ("stocks-fbs", fbs_res),
            )
            if isinstance(result, BaseException)
        )

    async with AsyncSessionLocal() as session:
        service = IngestionService(
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
            order_prices=order_prices,
            customer_price_regions=settings.wb_card_regions,
            write_offs=write_offs,
            keep_warehouses=keep_warehouses,
        )
        # Fresh WB data supersedes any manual matrix edits for these SKUs — the
        # product rule is that any refresh (nightly or a manual «Обновить»)
        # clears saved overrides. Run in the same transaction as the ingest.
        cleared = await MatrixOverrideRepository(session).delete_for_skus(nm_ids)
        if cleared:
            logger.info("Cleared %d manual matrix overrides after refresh.", cleared)
        await session.commit()

    return HarvestOutcome(
        counts={
            "funnel_rows": result.funnel_rows,
            "advertising_rows": result.advertising_rows,
            "search_zone_rows": result.search_zone_rows,
            "search_cluster_rows": result.search_cluster_rows,
            "stock_rows": result.stock_rows,
            "price_rows": result.price_rows,
            "sales_rows": result.sales_rows,
            "ad_write_off_rows": result.write_off_rows,
            "product_card_rows": card_count,
            "product_size_rows": size_count,
        },
        failed_sources=failed_sources,
    )
