"""The write-side facade over the per-family ingestion units.

:class:`IngestionService` keeps the exact constructor and public API the flat
``services/ingestion.py`` module exposed (Celery tasks and the DI wiring are
unchanged consumers); internally each fact family is handled by its own unit —
see the sibling modules — and :meth:`IngestionService.ingest_all` orchestrates
one full harvest across them.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.core.config import settings
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBAdvWriteOff,
    WBCampaign,
    WBCard,
    WBCardProduct,
    WBFunnelAggregateRow,
    WBFunnelHistoryRow,
    WBNormQueryItem,
    WBOrderRecord,
    WBPriceGood,
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
    OrderRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.schemas import CatalogIngestionResult, IngestionResult
from src.modules.monitoring.services.ingestion.advertising import AdvertisingIngestion
from src.modules.monitoring.services.ingestion.catalog import CatalogIngestion
from src.modules.monitoring.services.ingestion.funnel import FunnelIngestion
from src.modules.monitoring.services.ingestion.prices import PriceIngestion
from src.modules.monitoring.services.ingestion.sales import SalesIngestion
from src.modules.monitoring.services.ingestion.stocks import StockIngestion


class IngestionService:
    """Flattens and persists harvested WB statistics (facade over the units)."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        stock_repo: StockRepository,
        campaign_repo: CampaignRepository,
        product_card_repo: ProductCardRepository,
        product_size_repo: ProductSizeRepository,
        advertising_search_repo: AdvertisingSearchRepository,
        advertising_cluster_repo: AdvertisingClusterRepository,
        advertising_write_off_repo: AdvertisingWriteOffRepository,
        price_repo: PriceRepository,
        sale_repo: SaleRepository,
        order_repo: OrderRepository,
    ) -> None:
        """Wire each per-family ingestion unit from the injected repositories."""
        self._funnel = FunnelIngestion(funnel_repo)
        self._advertising = AdvertisingIngestion(
            advertising_repo=advertising_repo,
            campaign_repo=campaign_repo,
            advertising_search_repo=advertising_search_repo,
            advertising_cluster_repo=advertising_cluster_repo,
            advertising_write_off_repo=advertising_write_off_repo,
        )
        self._stocks = StockIngestion(stock_repo)
        self._prices = PriceIngestion(price_repo)
        self._sales = SalesIngestion(sale_repo, order_repo)
        self._catalog = CatalogIngestion(
            product_card_repo=product_card_repo,
            product_size_repo=product_size_repo,
        )

    # ------------------------------------------------------------------ #
    # Per-family delegates (see the unit classes for the full contracts)
    # ------------------------------------------------------------------ #
    async def ingest_sales_funnel(self, rows: list[WBFunnelHistoryRow]) -> int:
        """Delegate to :meth:`FunnelIngestion.ingest_sales_funnel`."""
        return await self._funnel.ingest_sales_funnel(rows)

    async def ingest_orders(self, records: list[WBOrderRecord]) -> int:
        """Delegate to :meth:`SalesIngestion.ingest_orders`."""
        return await self._sales.ingest_orders(records)

    async def ingest_funnel_cohorts(
        self, day: date, rows: list[WBFunnelAggregateRow], *, nm_ids: set[int] | None = None
    ) -> int:
        """Delegate to :meth:`FunnelIngestion.ingest_funnel_cohorts`."""
        return await self._funnel.ingest_funnel_cohorts(day, rows, nm_ids=nm_ids)

    async def ingest_funnel_backfill(
        self, day: date, rows: list[WBFunnelAggregateRow], *, nm_ids: set[int]
    ) -> int:
        """Delegate to :meth:`FunnelIngestion.ingest_funnel_backfill`."""
        return await self._funnel.ingest_funnel_backfill(day, rows, nm_ids=nm_ids)

    async def ingest_advertising(
        self,
        stats: list[WBAdvCampaignStats],
        *,
        window: tuple[date, date] | None = None,
    ) -> int:
        """Delegate to :meth:`AdvertisingIngestion.ingest_advertising`."""
        return await self._advertising.ingest_advertising(stats, window=window)

    async def ingest_write_offs(
        self,
        write_offs: list[WBAdvWriteOff],
        *,
        window: tuple[date, date],
    ) -> int:
        """Delegate to :meth:`AdvertisingIngestion.ingest_write_offs`."""
        return await self._advertising.ingest_write_offs(write_offs, window=window)

    async def ingest_campaigns(
        self,
        campaigns: list[WBCampaign],
        adverts: list[WBAdvertV2] | None = None,
    ) -> int:
        """Delegate to :meth:`AdvertisingIngestion.ingest_campaigns`."""
        return await self._advertising.ingest_campaigns(campaigns, adverts)

    async def ingest_search_stats(
        self,
        items: list[WBNormQueryItem],
        *,
        window: tuple[date, date] | None = None,
        requested_campaign_ids: list[int] | None = None,
    ) -> int:
        """Delegate to :meth:`AdvertisingIngestion.ingest_search_stats`."""
        return await self._advertising.ingest_search_stats(
            items, window=window, requested_campaign_ids=requested_campaign_ids
        )

    async def ingest_search_clusters(
        self,
        items: list[WBNormQueryItem],
        *,
        window: tuple[date, date] | None = None,
        requested_campaign_ids: list[int] | None = None,
    ) -> int:
        """Delegate to :meth:`AdvertisingIngestion.ingest_search_clusters`."""
        return await self._advertising.ingest_search_clusters(
            items, window=window, requested_campaign_ids=requested_campaign_ids
        )

    async def ingest_stocks(
        self,
        rows: list[WBStockRow],
        *,
        snapshot_date: date,
        harvested_nm_ids: list[int] | None = None,
        keep_warehouses: tuple[str, ...] = (),
    ) -> int:
        """Delegate to :meth:`StockIngestion.ingest_stocks`."""
        return await self._stocks.ingest_stocks(
            rows,
            snapshot_date=snapshot_date,
            harvested_nm_ids=harvested_nm_ids,
            keep_warehouses=keep_warehouses,
        )

    async def ingest_prices(
        self,
        goods: list[WBPriceGood],
        customer: list[WBCardProduct],
        *,
        snapshot_date: date,
        nm_ids: list[int] | None = None,
    ) -> int:
        """Delegate to :meth:`PriceIngestion.ingest_prices`."""
        return await self._prices.ingest_prices(
            goods, customer, snapshot_date=snapshot_date, nm_ids=nm_ids
        )

    async def ingest_sales(self, records: list[WBSaleRecord]) -> int:
        """Delegate to :meth:`SalesIngestion.ingest_sales`."""
        return await self._sales.ingest_sales(records)

    async def ingest_catalog(
        self, cards: list[WBCard], *, workspace_id: uuid.UUID
    ) -> CatalogIngestionResult:
        """Delegate to :meth:`CatalogIngestion.ingest_catalog`."""
        return await self._catalog.ingest_catalog(cards, workspace_id=workspace_id)

    # ------------------------------------------------------------------ #
    # Full-harvest orchestration
    # ------------------------------------------------------------------ #
    async def ingest_all(
        self,
        *,
        funnel: list[WBFunnelHistoryRow],
        advertising: list[WBAdvCampaignStats],
        stocks: list[WBStockRow],
        snapshot_date: date,
        harvested_nm_ids: list[int] | None = None,
        advertising_window: tuple[date, date] | None = None,
        search_stats: list[WBNormQueryItem] | None = None,
        search_requested_campaign_ids: list[int] | None = None,
        prices: list[WBPriceGood] | None = None,
        customer_prices: list[WBCardProduct] | None = None,
        price_nm_ids: list[int] | None = None,
        sales: list[WBSaleRecord] | None = None,
        orders: list[WBOrderRecord] | None = None,
        write_offs: list[WBAdvWriteOff] | None = None,
        keep_warehouses: tuple[str, ...] = (),
    ) -> IngestionResult:
        """Run a full harvest ingestion in one unit of work.

        Args:
            funnel: Raw per-product daily funnel-history rows to persist.
            advertising: Raw per-campaign stats trees to persist.
            stocks: Raw stock rows to persist.
            snapshot_date: Moscow-time day for the stock/price snapshot.
            harvested_nm_ids: Every SKU this harvest covered (enables the
                absence-means-zero stock sweep for sold-out SKUs).
            advertising_window: The harvested advertising window (enables the
                stale-row sweep before re-insert).
            search_stats: Raw normquery search-zone stats to persist; ``None``
                when the source failed (its rows are then left untouched).
            search_requested_campaign_ids: Every campaign the search-zone
                harvest asked for (enables its stale-row sweep).
            prices: Raw seller pricing records; ``None`` when the source failed.
            customer_prices: Raw storefront card products; ``None`` when that
                source failed (the customer side is then left ``NULL``).
            price_nm_ids: The harvested SKUs to snapshot prices for (scopes the
                account-wide seller feed to this harvest); ``None`` writes all.
            orders: Raw order lines; ``None`` when the source was not read or
                failed — which must leave the table untouched rather than
                sweeping a day to zero.
            sales: Raw per-item sale/return records; ``None`` when the source
                failed (existing rows are then left untouched).
            write_offs: Raw advertising write-offs naming who funded each charge;
                ``None`` when the source failed or was not asked for (the
                existing ledger is then left untouched, so a missed pass reads
                as «bonuses unknown» rather than «no bonuses»).
            keep_warehouses: Warehouses whose feeding source failed this run, so
                the sweep leaves their rows in place (FBO and FBS reach this
                table from different WB surfaces and fail independently).

        Returns:
            An :class:`IngestionResult` tallying rows persisted per family.
        """
        funnel_count = await self.ingest_sales_funnel(funnel)
        ad_count = await self.ingest_advertising(advertising, window=advertising_window)
        search_count = 0
        cluster_count = 0
        if search_stats is not None:
            search_count = await self.ingest_search_stats(
                search_stats,
                window=advertising_window,
                requested_campaign_ids=search_requested_campaign_ids,
            )
            # The same payload at its per-cluster grain (see the method's
            # docstring): the zone aggregate above sums the cluster texts away,
            # and «Поиск по кластерам» needs them.
            #
            # DORMANT (2026-09-09): gated off with the UI that read it. The
            # ingest costs no extra WB request — the payload is already in
            # hand — so the flag only decides whether the per-cluster rows are
            # written. Re-reading the flag's comment in core/config/
            # wildberries.py before flipping it is worth the minute: the
            # cluster series cannot be backfilled.
            if settings.wb_search_cluster_harvest_enabled:
                cluster_count = await self.ingest_search_clusters(
                    search_stats,
                    window=advertising_window,
                    requested_campaign_ids=search_requested_campaign_ids,
                )
        stock_count = await self.ingest_stocks(
            stocks,
            snapshot_date=snapshot_date,
            harvested_nm_ids=harvested_nm_ids,
            keep_warehouses=keep_warehouses,
        )
        # Prices snapshot: only written when the seller source succeeded (an
        # absent prices fetch must not stamp a NULL-price snapshot for the day).
        price_count = 0
        if prices is not None:
            price_count = await self.ingest_prices(
                prices, customer_prices or [], snapshot_date=snapshot_date, nm_ids=price_nm_ids
            )
        sales_count = 0
        if sales is not None:
            sales_count = await self.ingest_sales(sales)
        if orders is not None:
            await self.ingest_orders(orders)
        # The ledger is only ever swept and rewritten for the window it was
        # actually fetched for, so it needs the window to be known.
        write_off_count = 0
        if write_offs is not None and advertising_window is not None:
            write_off_count = await self.ingest_write_offs(write_offs, window=advertising_window)
        return IngestionResult(
            funnel_rows=funnel_count,
            advertising_rows=ad_count,
            search_zone_rows=search_count,
            search_cluster_rows=cluster_count,
            stock_rows=stock_count,
            price_rows=price_count,
            sales_rows=sales_count,
            write_off_rows=write_off_count,
        )
