"""Write-side ingestion service for the Monitoring module.

Consumes *raw, nested* WildBerries payloads (from the integration clients),
flattens the ``apps -> nms`` / conversion trees into clean relational records,
and persists them through repositories. Timestamps are normalized to Moscow
time (UTC+3) per the WB API global constraint before persistence.

This service is invoked by Celery tasks; it holds no HTTP/session logic itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBAdvertV2,
    WBCampaign,
    WBCard,
    WBFunnelHistoryRow,
    WBNormQueryItem,
    WBStockRow,
)
from src.modules.monitoring.models import normalize_status
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    ProductCardRepository,
    ProductSizeRepository,
    StockRepository,
)
from src.modules.monitoring.schemas import CatalogIngestionResult, IngestionResult

logger = get_logger(__name__)


@dataclass
class _SearchZoneAcc:
    """Mutable per-(date, campaign, SKU) accumulator over search clusters."""

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0


class IngestionService:
    """Flattens and persists harvested WB statistics."""

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
    ) -> None:
        """Inject the write repositories used for persistence."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._stocks = stock_repo
        self._campaigns = campaign_repo
        self._product_cards = product_card_repo
        self._product_sizes = product_size_repo
        self._advertising_search = advertising_search_repo

    async def ingest_sales_funnel(self, rows: list[WBFunnelHistoryRow]) -> int:
        """Flatten and upsert the daily organic sales-funnel history.

        Each product row carries a per-day ``history`` array; every day becomes
        one ``SalesFunnelDaily`` record keyed by ``(stat_date, nm_id)`` — the
        true daily granularity the baseline-demand normalization relies on.

        Args:
            rows: Raw per-product funnel-history rows from the analytics client.

        Returns:
            The number of daily funnel rows persisted.
        """
        flattened: list[dict[str, object]] = [
            {
                "stat_date": day.stat_date,
                "nm_id": row.nm_id,
                "open_count": day.open_count,
                "cart_count": day.cart_count,
                "order_count": day.order_count,
                "order_sum": day.order_sum,
                "buyout_count": day.buyout_count,
                "buyout_sum": day.buyout_sum,
                "add_to_wishlist": day.add_to_wishlist,
                "cart_conversion": day.cart_conversion,
                "order_conversion": day.order_conversion,
                "buyout_conversion": day.buyout_conversion,
            }
            for row in rows
            for day in row.history
        ]
        count = await self._funnel.upsert_many(flattened)
        logger.info("Ingested %d daily sales-funnel rows.", count)
        return count

    async def ingest_advertising(
        self,
        stats: list[WBAdvCampaignStats],
        *,
        window: tuple[date, date] | None = None,
    ) -> int:
        """Flatten the nested advertising trees and persist the records.

        Descends each campaign's ``days -> apps (platform) -> nms (SKU)`` into
        one flat record per ``(date, campaign_id, app_type, nm_id)`` and upserts
        all campaigns in a single batch.

        When ``window`` is supplied, each harvested campaign's rows inside that
        window are deleted first (same transaction). All-zero placeholder rows
        are skipped on insert, so without the sweep a WB correction from
        nonzero down to zero could never overwrite the stale value.

        Args:
            stats: Raw per-campaign full-stats trees from the advertising client.
            window: Optional inclusive ``(date_from, date_to)`` harvest window
                to sweep before inserting.

        Returns:
            The number of advertising rows persisted.
        """
        if window is not None and stats:
            deleted = await self._advertising.delete_window_for_campaigns(
                date_from=window[0],
                date_to=window[1],
                campaign_ids=[c.campaign_id for c in stats],
            )
            logger.info("Swept %d stale advertising rows before refresh.", deleted)

        flattened: list[dict[str, object]] = []
        for campaign in stats:
            for day in campaign.days:
                for app in day.apps:
                    for nm in app.nms:
                        # Skip WB's all-zero placeholder rows (e.g. the
                        # ``appType: 0`` buckets) — they carry no signal and
                        # only add noise to the per-campaign breakdown.
                        if (
                            nm.views == 0
                            and nm.clicks == 0
                            and nm.atbs == 0
                            and nm.sum == 0
                            and nm.orders == 0
                            and nm.sum_price == 0
                        ):
                            continue
                        flattened.append(
                            {
                                "stat_date": day.stat_date,
                                "campaign_id": campaign.campaign_id,
                                "app_type": app.app_type,
                                "nm_id": nm.nm_id,
                                "views": nm.views,
                                "clicks": nm.clicks,
                                "add_to_cart": nm.atbs,
                                "spend": nm.sum,
                                "orders": nm.orders,
                                "order_sum": nm.sum_price,
                            }
                        )
        count = await self._advertising.upsert_many(flattened)
        logger.info("Ingested %d advertising rows across %d campaigns.", count, len(stats))
        return count

    async def ingest_stocks(
        self,
        rows: list[WBStockRow],
        *,
        snapshot_date: date,
        harvested_nm_ids: list[int] | None = None,
    ) -> int:
        """Persist per-warehouse stock snapshots for a given day.

        Stored at the **size** grain ``(date, nm_id, warehouse, chrt_id)`` so the
        detail view can show which size sits in which warehouse. Rows are
        de-duplicated on that key (last one wins) to avoid an
        ``ON CONFLICT``-target cardinality violation should WB repeat a key.

        WB's report *omits* rows that dropped to zero, so the harvested SKUs'
        rows for the snapshot day are deleted first (same transaction) — a bare
        upsert would leave a stale "5 units" row behind on a same-day
        re-harvest after a sell-out, corrupting the out-of-stock signal.

        Args:
            rows: Raw per-size/per-warehouse stock rows from the analytics
                client.
            snapshot_date: The Moscow-time calendar day the snapshot represents.
            harvested_nm_ids: Every SKU this harvest covered (a superset of the
                SKUs present in ``rows``); defaults to the SKUs in ``rows`` —
                sufficient only when absence-means-zero cleanup is not needed.

        Returns:
            The number of size x warehouse rows persisted.
        """
        swept_ids = (
            harvested_nm_ids if harvested_nm_ids is not None else [row.nm_id for row in rows]
        )
        deleted = await self._stocks.delete_snapshot_day(
            snapshot_date=snapshot_date, nm_ids=swept_ids
        )
        if deleted:
            logger.info("Swept %d prior stock rows for %s before refresh.", deleted, snapshot_date)

        deduped: dict[tuple[int, str, int], WBStockRow] = {}
        for row in rows:
            deduped[(row.nm_id, row.warehouse_name, row.chrt_id)] = row

        flattened: list[dict[str, object]] = [
            {
                "stat_date": snapshot_date,
                "nm_id": row.nm_id,
                "warehouse_name": row.warehouse_name,
                "chrt_id": row.chrt_id,
                "region_name": row.region_name,
                "quantity": row.quantity,
                "in_way_to_client": row.in_way_to_client,
                "in_way_from_client": row.in_way_from_client,
            }
            for row in deduped.values()
        ]
        count = await self._stocks.upsert_many(flattened)
        logger.info("Ingested %d stock rows for %s.", count, snapshot_date)
        return count

    async def ingest_campaigns(
        self,
        campaigns: list[WBCampaign],
        adverts: list[WBAdvertV2] | None = None,
    ) -> int:
        """Upsert advertising-campaign metadata, enriched with v2 settings.

        ``promotion/count`` supplies the type/status backbone; ``adverts``
        (from ``/api/advert/v2/adverts``) decorates each campaign with its bid
        type, display-zone placements, name, and payment model — the fields the
        monitoring matrix classifies campaigns by. When ``adverts`` is ``None``
        (source failed or not requested) the settings columns are left
        untouched so a degraded harvest never wipes previously synced values.

        Args:
            campaigns: Flattened campaign descriptors from ``list_campaigns``.
            adverts: Optional campaign settings from ``list_adverts``.

        Returns:
            The number of campaign rows persisted.
        """
        adverts_by_id = {a.campaign_id: a for a in adverts or []}
        rows: list[dict[str, object]] = []
        for c in campaigns:
            row: dict[str, object] = {
                "campaign_id": c.campaign_id,
                "type": c.type,
                "status": c.status,
                "status_label": normalize_status(c.status),
            }
            if adverts is not None:
                advert = adverts_by_id.get(c.campaign_id)
                row["bid_type"] = advert.bid_type if advert else None
                row["placement_search"] = advert.settings.placements.search if advert else None
                row["placement_recommendations"] = (
                    advert.settings.placements.recommendations if advert else None
                )
                row["name"] = advert.settings.name if advert else None
                row["payment_type"] = advert.settings.payment_type if advert else None
            rows.append(row)
        count = await self._campaigns.upsert_many(rows, with_settings=adverts is not None)
        logger.info("Ingested %d campaign rows (%d with v2 settings).", count, len(adverts_by_id))
        return count

    async def ingest_search_stats(
        self,
        items: list[WBNormQueryItem],
        *,
        window: tuple[date, date] | None = None,
        requested_campaign_ids: list[int] | None = None,
    ) -> int:
        """Flatten and persist daily SEARCH-zone advertising slices.

        Each normquery item carries one ``dailyStats`` entry per day x search
        cluster; clusters are summed into one record per
        ``(date, campaign_id, nm_id)`` — the grain the analytics layer joins
        against the fullstats facts to split unified campaigns by zone.

        When ``window`` is supplied, the requested campaigns' rows inside it are
        deleted first (same transaction), mirroring the advertising sweep: a
        campaign whose search traffic dropped to zero would otherwise keep its
        stale slice forever.

        Args:
            items: Raw per-(campaign, SKU) search-cluster stats.
            window: Optional inclusive ``(date_from, date_to)`` harvest window
                to sweep before inserting.
            requested_campaign_ids: Every campaign the harvest asked stats for
                (a superset of the campaigns present in ``items``); defaults to
                the campaigns in ``items``.

        Returns:
            The number of search-zone rows persisted.
        """
        if window is not None:
            swept_ids = (
                requested_campaign_ids
                if requested_campaign_ids is not None
                else [item.campaign_id for item in items]
            )
            deleted = await self._advertising_search.delete_window_for_campaigns(
                date_from=window[0], date_to=window[1], campaign_ids=swept_ids
            )
            if deleted:
                logger.info("Swept %d stale search-zone rows before refresh.", deleted)

        accumulated: dict[tuple[date, int, int], _SearchZoneAcc] = {}
        for item in items:
            for daily in item.daily_stats:
                key = (daily.stat_date, item.campaign_id, item.nm_id)
                acc = accumulated.setdefault(key, _SearchZoneAcc())
                stat = daily.stat
                acc.views += stat.views
                acc.clicks += stat.clicks
                acc.add_to_cart += stat.atbs
                acc.spend += stat.spend
                acc.orders += stat.orders

        # All-zero day rows carry no signal — mirror the advertising skip.
        flattened: list[dict[str, object]] = [
            {
                "stat_date": stat_date,
                "campaign_id": campaign_id,
                "nm_id": nm_id,
                "views": acc.views,
                "clicks": acc.clicks,
                "add_to_cart": acc.add_to_cart,
                "spend": acc.spend,
                "orders": acc.orders,
            }
            for (stat_date, campaign_id, nm_id), acc in accumulated.items()
            if acc.views or acc.clicks or acc.add_to_cart or acc.spend or acc.orders
        ]
        count = await self._advertising_search.upsert_many(flattened)
        logger.info("Ingested %d search-zone rows from %d normquery items.", count, len(items))
        return count

    async def ingest_catalog(self, cards: list[WBCard]) -> CatalogIngestionResult:
        """Upsert the product catalogue dimensions from Content API cards.

        Splits each card into its identity row (``product_card``: vendor code +
        title) and one size row per variant (``product_size``: chrt_id ->
        human ``tech_size``). Sizes are de-duplicated on ``chrt_id`` (last one
        wins) to avoid an ``ON CONFLICT``-target cardinality violation should WB
        repeat a ``chrtID`` across cards.

        Args:
            cards: Raw product cards from the content client.

        Returns:
            A :class:`CatalogIngestionResult` tallying card + size rows persisted.
        """
        card_rows: list[dict[str, object]] = [
            {
                "nm_id": card.nm_id,
                "vendor_code": card.vendor_code,
                "title": card.title,
            }
            for card in cards
        ]

        deduped_sizes: dict[int, dict[str, object]] = {
            size.chrt_id: {
                "chrt_id": size.chrt_id,
                "nm_id": card.nm_id,
                "tech_size": size.tech_size,
                "wb_size": size.wb_size,
            }
            for card in cards
            for size in card.sizes
        }

        card_count = await self._product_cards.upsert_many(card_rows)
        size_count = await self._product_sizes.upsert_many(list(deduped_sizes.values()))
        logger.info(
            "Ingested catalogue: %d product cards, %d sizes.",
            card_count,
            size_count,
        )
        return CatalogIngestionResult(product_card_rows=card_count, product_size_rows=size_count)

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
    ) -> IngestionResult:
        """Run a full harvest ingestion in one unit of work.

        Args:
            funnel: Raw per-product daily funnel-history rows to persist.
            advertising: Raw per-campaign stats trees to persist.
            stocks: Raw stock rows to persist.
            snapshot_date: Moscow-time day for the stock snapshot.
            harvested_nm_ids: Every SKU this harvest covered (enables the
                absence-means-zero stock sweep for sold-out SKUs).
            advertising_window: The harvested advertising window (enables the
                stale-row sweep before re-insert).
            search_stats: Raw normquery search-zone stats to persist; ``None``
                when the source failed (its rows are then left untouched).
            search_requested_campaign_ids: Every campaign the search-zone
                harvest asked for (enables its stale-row sweep).

        Returns:
            An :class:`IngestionResult` tallying rows persisted per family.
        """
        funnel_count = await self.ingest_sales_funnel(funnel)
        ad_count = await self.ingest_advertising(advertising, window=advertising_window)
        search_count = 0
        if search_stats is not None:
            search_count = await self.ingest_search_stats(
                search_stats,
                window=advertising_window,
                requested_campaign_ids=search_requested_campaign_ids,
            )
        stock_count = await self.ingest_stocks(
            stocks, snapshot_date=snapshot_date, harvested_nm_ids=harvested_nm_ids
        )
        return IngestionResult(
            funnel_rows=funnel_count,
            advertising_rows=ad_count,
            search_zone_rows=search_count,
            stock_rows=stock_count,
        )
