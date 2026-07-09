"""Read-side analytics service for the Monitoring module.

Composes persisted funnel, advertising, and stock rows (fetched via injected
repositories) with the pure normalization pipeline to produce the summary
listing, detailed view, and cleansed funnel DTOs. It performs **no** SQL and
**no** HTTP — a textbook application service.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Protocol

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    Campaign,
    StockSnapshot,
    normalize_type,
)
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    CampaignRepository,
    FunnelRepository,
    ProductCardRepository,
    ProductSizeRepository,
    StockRepository,
)
from src.modules.monitoring.schemas import (
    CampaignAdvertising,
    CampaignDailyStat,
    FunnelDetailRead,
    FunnelResponseSchema,
    MetricWindow,
    SkuDetailResponse,
    SkuLookupItem,
    SkuLookupResponse,
    SkuSummaryItem,
    SkuSummaryListResponse,
    StockCell,
    StockDetail,
    StockSizeTotal,
    compute_ad_metrics,
    compute_funnel_totals,
)

#: Default look-back window (days) when the caller omits explicit dates.
_DEFAULT_WINDOW_DAYS = 30

#: Max SKUs returned by a vendor-code lookup (a partial code fans out to
#: every colourway; the frontend picker only needs a bounded shortlist).
_LOOKUP_LIMIT = 50


def resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Resolve an inclusive analysis window, applying defaults and validation.

    Application logic (not presentation): the router passes the raw optional
    query params straight through and this decides the effective window.

    Args:
        date_from: Optional inclusive start; defaults to ``date_to`` minus the
            default look-back window.
        date_to: Optional inclusive end; defaults to today.

    Returns:
        A validated ``(start, end)`` tuple.

    Raises:
        ValidationError: If the resolved start is after the end.
    """
    end = date_to or date.today()
    start = date_from or (end - timedelta(days=_DEFAULT_WINDOW_DAYS))
    if start > end:
        raise ValidationError("`date_from` must not be after `date_to`.")
    return start, end


class AnalyticsService:
    """Serves normalized monitoring analytics in summary and detail shapes."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        stock_repo: StockRepository,
        campaign_repo: CampaignRepository,
        product_card_repo: ProductCardRepository,
        product_size_repo: ProductSizeRepository,
    ) -> None:
        """Inject the read repositories the service composes over."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._stocks = stock_repo
        self._campaigns = campaign_repo
        self._product_cards = product_card_repo
        self._product_sizes = product_size_repo

    # ------------------------------------------------------------------ #
    # Summary listing
    # ------------------------------------------------------------------ #
    async def get_summary(
        self, *, date_from: date | None = None, date_to: date | None = None
    ) -> SkuSummaryListResponse:
        """Build a compact per-SKU summary listing over a date window.

        Args:
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).

        Returns:
            A :class:`SkuSummaryListResponse` with one item per SKU that has any
            funnel, advertising, or stock data in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_rows = await self._funnel.list_window(date_from=date_from, date_to=date_to)
        ad_rows = await self._advertising.list_window(date_from=date_from, date_to=date_to)
        stock_rows = await self._stocks.list_window(date_from=date_from, date_to=date_to)

        funnel_by_sku = _group_by_nm_id(funnel_rows)
        ad_by_sku = _group_by_nm_id(ad_rows)
        stock_by_sku = _group_by_nm_id(stock_rows)

        all_skus = sorted(set(funnel_by_sku) | set(ad_by_sku) | set(stock_by_sku))
        cards = await self._product_cards.get_by_ids(all_skus)

        items: list[SkuSummaryItem] = []
        for nm_id in all_skus:
            sku_funnel = funnel_by_sku.get(nm_id, [])
            sku_ads = ad_by_sku.get(nm_id, [])
            sku_stocks = stock_by_sku.get(nm_id, [])

            latest_stock = _latest_total_stock(sku_stocks)
            totals = compute_funnel_totals(sku_funnel)
            card = cards.get(nm_id)

            items.append(
                SkuSummaryItem(
                    nm_id=nm_id,
                    vendor_code=card.vendor_code if card else None,
                    title=card.title if card else None,
                    total_open_count=totals.open_count,
                    total_cart_count=totals.cart_count,
                    total_orders=totals.order_count,
                    total_order_sum=totals.order_sum,
                    total_buyout_count=totals.buyout_count,
                    total_buyout_sum=totals.buyout_sum,
                    total_add_to_wishlist=totals.add_to_wishlist,
                    cart_conversion=totals.cart_conversion,
                    order_conversion=totals.order_conversion,
                    buyout_conversion=totals.buyout_conversion,
                    total_ad_spend=float(sum(r.spend for r in sku_ads)),
                    total_ad_clicks=sum(r.clicks for r in sku_ads),
                    latest_stock=latest_stock,
                    is_out_of_stock=latest_stock <= 0,
                )
            )

        return SkuSummaryListResponse(
            window=MetricWindow(start=date_from, end=date_to),
            count=len(items),
            items=items,
        )

    # ------------------------------------------------------------------ #
    # Detailed view
    # ------------------------------------------------------------------ #
    async def get_detail(
        self,
        *,
        nm_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        campaign_id: int | None = None,
        campaign_status: str | None = None,
    ) -> SkuDetailResponse:
        """Build the full detailed view for a single SKU.

        Advertising is grouped per campaign (each with totals + daily breakdown
        and its campaign status), and can be filtered to a single campaign or to
        campaigns of a given status. Stock is returned as a summary total plus a
        size x warehouse breakdown.

        Args:
            nm_id: WB SKU identifier.
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).
            campaign_id: Optional filter — only this campaign's advertising.
            campaign_status: Optional filter — only campaigns whose normalized
                status matches (e.g. ``active``/``paused``/``completed``).

        Returns:
            A :class:`SkuDetailResponse` combining funnel, per-campaign
            advertising, and stock breakdowns plus the cleansed baseline demand.

        Raises:
            NotFoundError: If the SKU has no data of any kind in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_rows = await self._funnel.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        ad_rows = await self._advertising.list_for_sku(
            nm_id=nm_id,
            date_from=date_from,
            date_to=date_to,
            campaign_id=campaign_id,
        )
        stock_rows = await self._stocks.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )

        if not funnel_rows and not ad_rows and not stock_rows:
            raise NotFoundError(f"No monitoring data found for SKU {nm_id}.")

        # Resolve campaign metadata for the SKU's campaigns, then group + filter.
        campaign_ids = {row.campaign_id for row in ad_rows}
        campaigns = await self._campaigns.get_by_ids(campaign_ids)
        advertising = _build_campaign_advertising(ad_rows, campaigns)
        if campaign_status is not None:
            advertising = [c for c in advertising if c.status_label == campaign_status]

        # Decorate identity + sizes from the catalogue dimensions (nullable —
        # a SKU with stock but no synced card still renders, just label-less).
        card = (await self._product_cards.get_by_ids([nm_id])).get(nm_id)
        size_labels = await self._product_sizes.get_labels_by_chrt_ids(
            {row.chrt_id for row in stock_rows}
        )

        return SkuDetailResponse(
            nm_id=nm_id,
            vendor_code=card.vendor_code if card else None,
            title=card.title if card else None,
            window=MetricWindow(start=date_from, end=date_to),
            funnel=[FunnelDetailRead.model_validate(r) for r in funnel_rows],
            funnel_totals=compute_funnel_totals(funnel_rows),
            advertising=advertising,
            stock=_build_stock_detail(stock_rows, size_labels),
        )

    # ------------------------------------------------------------------ #
    # Raw funnel
    # ------------------------------------------------------------------ #
    async def get_sku_funnel(
        self,
        sku: int,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> FunnelResponseSchema:
        """Return the raw organic sales funnel for a single SKU.

        Args:
            sku: WB SKU identifier (``nm_id``).
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).

        Returns:
            A populated :class:`FunnelResponseSchema` (raw per-day metrics).

        Raises:
            NotFoundError: If the SKU has no funnel data in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_rows = await self._funnel.list_for_sku(
            nm_id=sku, date_from=date_from, date_to=date_to
        )
        if not funnel_rows:
            raise NotFoundError(f"No funnel metrics found for SKU {sku}.")

        return FunnelResponseSchema(
            nm_id=sku,
            window_start=date_from,
            window_end=date_to,
            raw_orders=sum(r.order_count for r in funnel_rows),
            totals=compute_funnel_totals(funnel_rows),
            days=[FunnelDetailRead.model_validate(r) for r in funnel_rows],
        )

    # ------------------------------------------------------------------ #
    # Vendor-code lookup
    # ------------------------------------------------------------------ #
    async def lookup_skus_by_vendor_code(self, vendor_code: str) -> SkuLookupResponse:
        """Resolve a seller vendor code (or fragment) to matching SKUs.

        Backs the frontend's "или артикулу продавца" search: it turns a code
        like ``"M-TRX01-BLK"`` (or a prefix like ``"M-TRX01"``) into the
        concrete ``nm_id``\\ (s) the other endpoints key on. Matching is
        case-insensitive and substring-based, so a partial code fans out to every
        colourway.

        Args:
            vendor_code: The vendor code or fragment to search for.

        Returns:
            A :class:`SkuLookupResponse` of matching SKUs, ordered by vendor code
            (empty when nothing matches).

        Raises:
            ValidationError: If ``vendor_code`` is blank.
        """
        fragment = vendor_code.strip()
        if not fragment:
            raise ValidationError("`vendor_code` must not be blank.")

        cards = await self._product_cards.search_by_vendor_code(fragment, limit=_LOOKUP_LIMIT)
        return SkuLookupResponse(
            query=fragment,
            count=len(cards),
            items=[
                SkuLookupItem(
                    nm_id=card.nm_id,
                    vendor_code=card.vendor_code,
                    title=card.title,
                )
                for card in cards
            ],
        )


class _HasNmId(Protocol):
    """Structural type for any ORM row exposing an ``nm_id`` SKU key."""

    nm_id: int


def _group_by_nm_id[RowT: _HasNmId](rows: list[RowT]) -> dict[int, list[RowT]]:
    """Group any ``nm_id``-bearing ORM rows into a dict keyed by SKU."""
    grouped: dict[int, list[RowT]] = defaultdict(list)
    for row in rows:
        grouped[row.nm_id].append(row)
    return grouped


def _latest_total_stock(stock_rows: list[StockSnapshot]) -> int:
    """Sum stock across all sizes/warehouses for the most recent snapshot date."""
    if not stock_rows:
        return 0
    latest_day = max(row.stat_date for row in stock_rows)
    return sum(r.quantity for r in stock_rows if r.stat_date == latest_day)


def _build_campaign_advertising(
    ad_rows: list[AdvertisingStatDaily],
    campaigns: dict[int, Campaign],
) -> list[CampaignAdvertising]:
    """Group flat advertising rows into per-campaign views with totals.

    Args:
        ad_rows: The SKU's advertising rows (already window/campaign filtered).
        campaigns: Campaign metadata keyed by ``campaign_id`` (may be partial).

    Only campaigns that actually **delivered** ads for this SKU in the window
    (views > 0, clicks > 0, or spend > 0) are included — campaigns with merely
    attribution-window orders (0 views/clicks/spend) are dropped as noise.

    Returns:
        One :class:`CampaignAdvertising` per delivering campaign, ordered by
        descending spend, each carrying totals, derived CPM/CTR/CPC, and a
        per-day/platform breakdown.
    """
    by_campaign: dict[int, list[AdvertisingStatDaily]] = defaultdict(list)
    for row in ad_rows:
        by_campaign[row.campaign_id].append(row)

    result: list[CampaignAdvertising] = []
    for campaign_id, rows in by_campaign.items():
        views = sum(r.views for r in rows)
        clicks = sum(r.clicks for r in rows)
        add_to_cart = sum(r.add_to_cart for r in rows)
        spend = float(sum(r.spend for r in rows))
        orders = sum(r.orders for r in rows)
        # Drop campaigns that did not deliver any ads for this SKU.
        if views == 0 and clicks == 0 and spend == 0:
            continue

        meta = campaigns.get(campaign_id)
        result.append(
            CampaignAdvertising(
                campaign_id=campaign_id,
                type=meta.type if meta else None,
                type_label=normalize_type(meta.type) if meta else None,
                status=meta.status if meta else None,
                status_label=meta.status_label if meta else None,
                views=views,
                clicks=clicks,
                add_to_cart=add_to_cart,
                spend=spend,
                orders=orders,
                metrics=compute_ad_metrics(
                    views=views,
                    clicks=clicks,
                    add_to_cart=add_to_cart,
                    spend=spend,
                    orders=orders,
                ),
                daily=[
                    CampaignDailyStat(
                        stat_date=r.stat_date,
                        app_type=r.app_type,
                        views=r.views,
                        clicks=r.clicks,
                        add_to_cart=r.add_to_cart,
                        spend=float(r.spend),
                        orders=r.orders,
                        metrics=compute_ad_metrics(
                            views=r.views,
                            clicks=r.clicks,
                            add_to_cart=r.add_to_cart,
                            spend=float(r.spend),
                            orders=r.orders,
                        ),
                    )
                    for r in rows
                ],
            )
        )
    result.sort(key=lambda c: c.spend, reverse=True)
    return result


def _build_stock_detail(
    stock_rows: list[StockSnapshot], size_labels: dict[int, str]
) -> StockDetail:
    """Build the stock summary + size x warehouse breakdown for a SKU.

    Uses only the most recent snapshot date (stock is a point-in-time snapshot,
    not a series), so the detail reflects current stock rather than summing
    across every harvested day. Each ``chrt_id`` is decorated with its human
    ``tech_size`` from ``size_labels`` (``None`` when the catalogue has not been
    synced for that size yet, so old rows keep working).

    Args:
        stock_rows: The SKU's stock rows across the window.
        size_labels: Map of ``chrt_id -> tech_size`` for the SKU's sizes.

    Returns:
        A populated :class:`StockDetail` (all zeros/empty when no stock exists).
    """
    if not stock_rows:
        return StockDetail(
            total_quantity=0,
            total_in_way_to_client=0,
            total_in_way_from_client=0,
        )

    latest_day = max(row.stat_date for row in stock_rows)
    latest = [r for r in stock_rows if r.stat_date == latest_day]

    by_size: dict[int, int] = defaultdict(int)
    for row in latest:
        by_size[row.chrt_id] += row.quantity

    return StockDetail(
        total_quantity=sum(r.quantity for r in latest),
        total_in_way_to_client=sum(r.in_way_to_client for r in latest),
        total_in_way_from_client=sum(r.in_way_from_client for r in latest),
        by_size=[
            StockSizeTotal(
                chrt_id=chrt_id,
                tech_size=size_labels.get(chrt_id),
                quantity=qty,
            )
            for chrt_id, qty in sorted(by_size.items())
        ],
        cells=[
            StockCell(
                chrt_id=r.chrt_id,
                tech_size=size_labels.get(r.chrt_id),
                warehouse_name=r.warehouse_name,
                region_name=r.region_name,
                quantity=r.quantity,
                in_way_to_client=r.in_way_to_client,
                in_way_from_client=r.in_way_from_client,
            )
            for r in latest
        ],
    )
