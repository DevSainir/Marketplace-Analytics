"""The per-SKU summary listing and the vendor-code lookup."""

from __future__ import annotations

import uuid
from datetime import date

from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    FunnelRepository,
    PriceRepository,
    ProductCardRepository,
    SaleRepository,
    StockRepository,
)
from src.modules.monitoring.schemas import (
    MetricWindow,
    SkuLookupItem,
    SkuLookupResponse,
    SkuSummaryItem,
    SkuSummaryListResponse,
)
from src.modules.monitoring.services.analytics.window import resolve_window

#: Max SKUs returned by a vendor-code lookup (a partial code fans out to
#: every colourway; the frontend picker only needs a bounded shortlist).
_LOOKUP_LIMIT = 50


class SummaryAnalytics:
    """Serves the workspace-wide SKU listing and the vendor-code search."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        stock_repo: StockRepository,
        price_repo: PriceRepository,
        sale_repo: SaleRepository,
        product_card_repo: ProductCardRepository,
    ) -> None:
        """Inject the read repositories the listing composes over."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._stocks = stock_repo
        self._prices = price_repo
        self._sales = sale_repo
        self._product_cards = product_card_repo

    async def list_workspace_nm_ids(self, *, workspace_id: uuid.UUID) -> list[int]:
        """Return every SKU registered to the workspace.

        Backs the bulk "Refresh all SKUs" refresh: the route enqueues a harvest
        over exactly this list.
        """
        return await self._product_cards.list_workspace_nm_ids(workspace_id)

    async def get_summary(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SkuSummaryListResponse:
        """Build a compact per-SKU summary listing over a date window.

        All rollups are aggregated by the database (one row per SKU), so the
        request's memory footprint is O(SKUs on the page), never O(fact rows in
        the window).

        Args:
            workspace_id: The caller's active workspace; every aggregate is
                restricted to its SKUs, so other workspaces' SKUs never appear.
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).
            limit: Page size (bounded by the router).
            offset: Page offset into the SKU list (in-stock SKUs first, then by
                window orders descending, then ``nm_id``).

        Returns:
            A :class:`SkuSummaryListResponse` with one item per SKU that has any
            funnel, advertising, or stock data in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_aggs = await self._funnel.aggregate_window(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        ad_aggs = await self._advertising.aggregate_window(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        stock_totals = await self._stocks.latest_totals_by_sku(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        # "Orders, ₽" prices window-total counts against each SKU's LATEST known
        # seller price; buyouts come from the sale-date records (real revenue).
        latest_prices = await self._prices.latest_by_sku(
            workspace_id=workspace_id, date_to=max(date_to, moscow_today())
        )
        sale_totals = await self._sales.window_totals_by_sku(
            workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )

        funnel_by_sku = {agg.nm_id: agg for agg in funnel_aggs}
        ads_by_sku = {agg.nm_id: agg for agg in ad_aggs}

        def _sku_order(nm_id: int) -> tuple[bool, int, int]:
            """In-stock SKUs first, most window orders next, ``nm_id`` as the tiebreak."""
            funnel = funnel_by_sku.get(nm_id)
            return (
                stock_totals.get(nm_id, 0) <= 0,
                -(funnel.order_count if funnel else 0),
                nm_id,
            )

        all_skus = sorted(set(funnel_by_sku) | set(ads_by_sku) | set(stock_totals), key=_sku_order)
        total = len(all_skus)
        page_skus = all_skus[offset : offset + limit]
        cards = await self._product_cards.get_by_ids(page_skus)

        items: list[SkuSummaryItem] = []
        for nm_id in page_skus:
            funnel = funnel_by_sku.get(nm_id)
            ads = ads_by_sku.get(nm_id)
            latest_stock = stock_totals.get(nm_id, 0)
            card = cards.get(nm_id)

            open_count = funnel.open_count if funnel else 0
            cart_count = funnel.cart_count if funnel else 0
            order_count = funnel.order_count if funnel else 0
            # "Orders, ₽": window-total count x latest seller price. Buyouts are
            # sale-date attributed facts from the Statistics records.
            seller_price = latest_prices.get(nm_id, (None, None))[0]
            order_sum = round(order_count * seller_price, 2) if seller_price is not None else 0.0
            sale = sale_totals.get(nm_id)
            buyout_count = sale.buyout_count if sale else 0
            buyout_sum = sale.buyout_sum if sale else 0.0
            return_count = sale.return_count if sale else 0

            items.append(
                SkuSummaryItem(
                    nm_id=nm_id,
                    vendor_code=card.vendor_code if card else None,
                    title=card.title if card else None,
                    photo_url=(card.photo_url or None) if card else None,
                    total_open_count=open_count,
                    total_cart_count=cart_count,
                    total_orders=order_count,
                    total_order_sum=order_sum,
                    total_buyout_count=buyout_count,
                    total_buyout_sum=buyout_sum,
                    total_return_count=return_count,
                    total_add_to_wishlist=funnel.add_to_wishlist if funnel else 0,
                    # Conversions are recomputed from window totals (never
                    # averaged across days), matching compute_funnel_totals.
                    cart_conversion=(
                        round(cart_count / open_count * 100, 2) if open_count else 0.0
                    ),
                    order_conversion=(
                        round(order_count / cart_count * 100, 2) if cart_count else 0.0
                    ),
                    # No buyout ratio here on purpose. This feed sees returns, not
                    # refusals at pickup, so any ratio built from it answers a
                    # different question than "Buyout rate" — the old
                    # `buyout_conversion` divided by returns and read 90% where WB
                    # said ~30% (one card, checked 2026-07-16). "Buyout rate"
                    # is the matrix's `buyout_percent`; see SkuSummaryItem.
                    total_ad_spend=ads.spend if ads else 0.0,
                    total_ad_clicks=ads.clicks if ads else 0,
                    latest_stock=latest_stock,
                    is_out_of_stock=latest_stock <= 0,
                )
            )

        return SkuSummaryListResponse(
            window=MetricWindow(start=date_from, end=date_to),
            count=len(items),
            total=total,
            limit=limit,
            offset=offset,
            items=items,
        )

    async def lookup_skus_by_vendor_code(
        self, vendor_code: str, *, workspace_id: uuid.UUID
    ) -> SkuLookupResponse:
        """Resolve a seller vendor code (or fragment) to matching SKUs.

        Backs the frontend's search by seller article code ("or vendor
        code"): it turns a code like ``"M-TRX01-BLK"`` (or a prefix like
        ``"M-TRX01"``) into the concrete ``nm_id``\\ (s) the other endpoints key on.
        Matching is case-insensitive and substring-based, so a partial code fans
        out to every colourway.

        Args:
            vendor_code: The vendor code or fragment to search for.
            workspace_id: The caller's active workspace (only its SKUs match).

        Returns:
            A :class:`SkuLookupResponse` of matching SKUs, ordered by vendor code
            (empty when nothing matches).

        Raises:
            ValidationError: If ``vendor_code`` is blank.
        """
        fragment = vendor_code.strip()
        if not fragment:
            raise ValidationError("Enter a vendor code.")

        cards = await self._product_cards.search_by_vendor_code(
            fragment, workspace_id=workspace_id, limit=_LOOKUP_LIMIT
        )
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
