"""Read-side analytics service for the Monitoring module.

Composes persisted funnel, advertising, and stock rows (fetched via injected
repositories) with the pure normalization pipeline to produce the summary
listing, detailed view, and cleansed funnel DTOs. It performs **no** SQL and
**no** HTTP — a textbook application service.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.core.exceptions import NotFoundError, ValidationError
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
    StockSnapshot,
    normalize_type,
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
    WarehouseMarkRepository,
)
from src.modules.monitoring.repos.sales import SaleDailyTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas import (
    BaselineDemandRead,
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
    WarehouseMarksResponse,
    compute_ad_metrics,
    compute_funnel_totals,
)
from src.modules.monitoring.schemas.matrix import (
    MatrixBaseState,
    MatrixCellEdit,
    MatrixPreviewResponse,
)
from src.modules.monitoring.services.matrix import (
    BUYOUT_LAG_START_DAYS,
    build_matrix_from_base,
    derive_base_state,
    price_for_day,
)
from src.modules.monitoring.services.matrix_edit import apply_edit
from src.modules.monitoring.services.matrix_overrides import (
    diff_to_overrides,
    overlay_overrides,
)
from src.modules.monitoring.services.normalization import (
    DailyDemandPoint,
    compute_baseline_demand,
)

#: Default look-back window (days) when the caller omits explicit dates.
_DEFAULT_WINDOW_DAYS = 30

#: Hard ceiling on a requested window. Bounds the work any single request can
#: demand (an unbounded `date_from=2000-01-01` was a memory/latency DoS).
_MAX_WINDOW_DAYS = 366

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
        date_to: Optional inclusive end; defaults to today in Moscow time —
            WB data is dated by the Moscow calendar day, so a UTC server's
            ``date.today()`` would misalign the window between 00:00-03:00 MSK.

    Returns:
        A validated ``(start, end)`` tuple.

    Raises:
        ValidationError: If the resolved start is after the end, or the window
            exceeds :data:`_MAX_WINDOW_DAYS`.
    """
    end = date_to or moscow_today()
    start = date_from or (end - timedelta(days=_DEFAULT_WINDOW_DAYS))
    if start > end:
        raise ValidationError("`date_from` must not be after `date_to`.")
    if (end - start).days > _MAX_WINDOW_DAYS:
        raise ValidationError(f"The analysis window must not exceed {_MAX_WINDOW_DAYS} days.")
    return start, end


class AnalyticsService:
    """Serves normalized monitoring analytics in summary and detail shapes."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        advertising_search_repo: AdvertisingSearchRepository,
        stock_repo: StockRepository,
        campaign_repo: CampaignRepository,
        product_card_repo: ProductCardRepository,
        product_size_repo: ProductSizeRepository,
        matrix_override_repo: MatrixOverrideRepository,
        price_repo: PriceRepository,
        sale_repo: SaleRepository,
        warehouse_mark_repo: WarehouseMarkRepository,
    ) -> None:
        """Inject the read repositories the service composes over."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._advertising_search = advertising_search_repo
        self._stocks = stock_repo
        self._campaigns = campaign_repo
        self._product_cards = product_card_repo
        self._product_sizes = product_size_repo
        self._matrix_overrides = matrix_override_repo
        self._prices = price_repo
        self._sales = sale_repo
        self._warehouse_marks = warehouse_mark_repo

    # ------------------------------------------------------------------ #
    # Summary listing
    # ------------------------------------------------------------------ #
    async def get_summary(
        self,
        *,
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
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).
            limit: Page size (bounded by the router).
            offset: Page offset into the SKU list (ordered by ``nm_id``).

        Returns:
            A :class:`SkuSummaryListResponse` with one item per SKU that has any
            funnel, advertising, or stock data in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_aggs = await self._funnel.aggregate_window(date_from=date_from, date_to=date_to)
        ad_aggs = await self._advertising.aggregate_window(date_from=date_from, date_to=date_to)
        stock_totals = await self._stocks.latest_totals_by_sku(date_from=date_from, date_to=date_to)
        # «Заказы, ₽» prices window-total counts against each SKU's LATEST known
        # seller price; buyouts come from the sale-date records (real revenue).
        latest_prices = await self._prices.latest_by_sku(date_to=max(date_to, moscow_today()))
        sale_totals = await self._sales.window_totals_by_sku(date_from=date_from, date_to=date_to)

        funnel_by_sku = {agg.nm_id: agg for agg in funnel_aggs}
        ads_by_sku = {agg.nm_id: agg for agg in ad_aggs}

        all_skus = sorted(set(funnel_by_sku) | set(ads_by_sku) | set(stock_totals))
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
            # «Заказы, ₽»: window-total count x latest seller price. Buyouts are
            # sale-date attributed facts from the Statistics records.
            seller_price = latest_prices.get(nm_id, (None, None))[0]
            order_sum = round(order_count * seller_price, 2) if seller_price is not None else 0.0
            sale = sale_totals.get(nm_id)
            buyout_count = sale.buyout_count if sale else 0
            buyout_sum = sale.buyout_sum if sale else 0.0
            decided = buyout_count + (sale.return_count if sale else 0)

            items.append(
                SkuSummaryItem(
                    nm_id=nm_id,
                    vendor_code=card.vendor_code if card else None,
                    title=card.title if card else None,
                    total_open_count=open_count,
                    total_cart_count=cart_count,
                    total_orders=order_count,
                    total_order_sum=order_sum,
                    total_buyout_count=buyout_count,
                    total_buyout_sum=buyout_sum,
                    total_add_to_wishlist=funnel.add_to_wishlist if funnel else 0,
                    # Conversions are recomputed from window totals (never
                    # averaged across days), matching compute_funnel_totals.
                    cart_conversion=(
                        round(cart_count / open_count * 100, 2) if open_count else 0.0
                    ),
                    order_conversion=(
                        round(order_count / cart_count * 100, 2) if cart_count else 0.0
                    ),
                    # WB's definition: buyouts over DECIDED deliveries
                    # (accepted + returned) inside the window.
                    buyout_conversion=(round(buyout_count / decided * 100, 2) if decided else 0.0),
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
        # The funnel is fetched over an EXTENDED window: the matrix's lagged
        # «Процент выкупа» reads up to BUYOUT_LAG_START_DAYS before the first
        # displayed day. Everything else uses the requested window's slice.
        (
            extended_funnel_rows,
            ad_rows,
            search_rows,
            campaigns,
            price_snapshots,
            stock_daily,
            sales_daily,
        ) = await self._fetch_matrix_inputs(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        funnel_rows = [row for row in extended_funnel_rows if row.stat_date >= date_from]
        # The per-day stock totals feed both the matrix stock/in-transit rows
        # and OOS masking; the latest snapshot's size x warehouse rows feed the
        # breakdown table (filtered in SQL, not hydrated wholesale).
        stock_daily_totals = {total.stat_date: total.quantity for total in stock_daily}
        latest_stock_rows = await self._stocks.list_latest_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )

        if not funnel_rows and not ad_rows and not stock_daily:
            raise NotFoundError(f"No monitoring data found for SKU {nm_id}.")

        # Group + filter the per-campaign advertising view.
        advertising = _build_campaign_advertising(ad_rows, campaigns)
        if campaign_status is not None:
            advertising = [c for c in advertising if c.status_label == campaign_status]

        # Derive the matrix input working copy, then overlay any manual edits
        # so the served matrix (and the editable base) reflect saved overrides.
        base = derive_base_state(
            date_from=date_from,
            date_to=date_to,
            funnel_rows=extended_funnel_rows,
            ad_rows=ad_rows,
            search_rows=search_rows,
            campaigns=campaigns,
            price_snapshots=price_snapshots,
            stock_daily=stock_daily,
            sales_daily=sales_daily,
        )
        overrides = await self._matrix_overrides.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        overlay_overrides(base, overrides)

        # The raw funnel list/totals carry the same price-derived ₽ volumes
        # (count x carry-forward seller price) the matrix «Общая» column shows.
        funnel_details, window_order_sum, window_buyout_sum = _price_funnel_details(
            funnel_rows, price_snapshots
        )

        # Decorate identity + sizes from the catalogue dimensions (nullable —
        # a SKU with stock but no synced card still renders, just label-less).
        card = (await self._product_cards.get_by_ids([nm_id])).get(nm_id)
        size_labels = await self._product_sizes.get_labels_by_chrt_ids(
            {row.chrt_id for row in latest_stock_rows}
        )
        marked_warehouses = await self._warehouse_marks.list_names(nm_id=nm_id)

        return SkuDetailResponse(
            nm_id=nm_id,
            vendor_code=card.vendor_code if card else None,
            title=card.title if card else None,
            window=MetricWindow(start=date_from, end=date_to),
            funnel=funnel_details,
            funnel_totals=compute_funnel_totals(
                funnel_rows, order_sum=window_order_sum, buyout_sum=window_buyout_sum
            ),
            baseline_demand=_compute_baseline(funnel_rows, stock_daily_totals),
            advertising=advertising,
            matrix=build_matrix_from_base(base),
            matrix_base=base,
            stock=_build_stock_detail(latest_stock_rows, size_labels, marked_warehouses),
        )

    async def set_warehouse_mark(
        self, *, nm_id: int, warehouse_name: str, marked: bool
    ) -> WarehouseMarksResponse:
        """Set or clear the «Отгрузить» mark on one warehouse of one SKU.

        Marks are per-SKU: marking a warehouse for one nm_id never affects any
        other SKU. Both directions are idempotent.

        Args:
            nm_id: WB SKU identifier.
            warehouse_name: WB warehouse name as reported by the stocks report.
            marked: ``True`` to mark, ``False`` to unmark.

        Returns:
            The SKU's marked warehouse names after the update.
        """
        if marked:
            await self._warehouse_marks.add(nm_id=nm_id, warehouse_name=warehouse_name)
        else:
            await self._warehouse_marks.remove(nm_id=nm_id, warehouse_name=warehouse_name)
        return WarehouseMarksResponse(
            marked_warehouses=await self._warehouse_marks.list_names(nm_id=nm_id)
        )

    async def _fetch_matrix_inputs(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        campaign_id: int | None = None,
    ) -> tuple[
        list[SalesFunnelDaily],
        list[AdvertisingStatDaily],
        list[AdvertisingSearchStatDaily],
        dict[int, Campaign],
        list[PriceSnapshot],
        list[StockDailyTotal],
        list[SaleDailyTotal],
    ]:
        """Fetch the fact rows the matrix is derived from (extended funnel window).

        Shared by the detail read and the save path so both derive an identical
        fact-base. The funnel spans ``[date_from - BUYOUT_LAG_START_DAYS, date_to]``
        for the lagged «Процент выкупа»; price snapshots share that extended
        window so early display days can carry an earlier price forward.
        """
        extended_start = date_from - timedelta(days=BUYOUT_LAG_START_DAYS)
        extended_funnel_rows = await self._funnel.list_for_sku(
            nm_id=nm_id,
            date_from=extended_start,
            date_to=date_to,
        )
        ad_rows = await self._advertising.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        search_rows = await self._advertising_search.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        campaigns = await self._campaigns.get_by_ids({row.campaign_id for row in ad_rows})
        # Prices/stock are snapshotted on the harvest day (Moscow *today*), but
        # the analysis window ends *yesterday* (WB serves no current-day
        # funnel), so the latest snapshot sits just outside [.., date_to]. Reach
        # up to today so carry-forward can apply it to the recent display days.
        snapshot_end = max(date_to, moscow_today())
        price_snapshots = await self._prices.list_for_sku(
            nm_id=nm_id, date_from=extended_start, date_to=snapshot_end
        )
        stock_daily = await self._stocks.daily_totals_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=snapshot_end
        )
        # Sale-date buyout/return totals: unlike the funnel, sales for the
        # current day already exist — reach up to today like the snapshots.
        sales_daily = await self._sales.daily_totals_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=snapshot_end
        )
        return (
            extended_funnel_rows,
            ad_rows,
            search_rows,
            campaigns,
            price_snapshots,
            stock_daily,
            sales_daily,
        )

    # ------------------------------------------------------------------ #
    # Matrix editing (preview + save)
    # ------------------------------------------------------------------ #
    def preview_matrix_edit(
        self, base: MatrixBaseState, edit: MatrixCellEdit
    ) -> MatrixPreviewResponse:
        """Apply one pending cell-edit to a working copy and recompute (no I/O).

        Pure recomputation: the client holds the working copy, this resolves the
        edit into its inputs and re-derives the display matrix. Nothing is
        persisted — that is what :meth:`save_matrix` does.

        Args:
            base: The client's current input working copy.
            edit: The cell the user just changed.

        Returns:
            The recomputed working copy and display matrix.

        Raises:
            ValidationError: If the edit targets a read-only / non-invertible cell.
        """
        new_base = apply_edit(base, edit)
        return MatrixPreviewResponse(base=new_base, matrix=build_matrix_from_base(new_base))

    async def save_matrix(
        self,
        *,
        nm_id: int,
        base: MatrixBaseState,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> SkuDetailResponse:
        """Persist a working copy as overrides, then return the refreshed detail.

        The working copy is diffed against a freshly fact-derived base; only the
        input cells that actually changed are stored (a cell edited back to its
        harvested value drops its override). Existing overrides for the window
        are replaced in one transaction.

        Args:
            nm_id: WB SKU identifier.
            base: The working copy to persist.
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).

        Returns:
            The detail view rebuilt with the saved overrides applied.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        (
            extended_funnel_rows,
            ad_rows,
            search_rows,
            campaigns,
            price_snapshots,
            stock_daily,
            sales_daily,
        ) = await self._fetch_matrix_inputs(nm_id=nm_id, date_from=date_from, date_to=date_to)
        fact_base = derive_base_state(
            date_from=date_from,
            date_to=date_to,
            funnel_rows=extended_funnel_rows,
            ad_rows=ad_rows,
            search_rows=search_rows,
            campaigns=campaigns,
            price_snapshots=price_snapshots,
            stock_daily=stock_daily,
            sales_daily=sales_daily,
        )
        rows = diff_to_overrides(nm_id=nm_id, working=base, fact=fact_base)
        await self._matrix_overrides.replace_window(
            nm_id=nm_id, date_from=date_from, date_to=date_to, rows=rows
        )
        return await self.get_detail(nm_id=nm_id, date_from=date_from, date_to=date_to)

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

        price_snapshots = await self._prices.list_for_sku(
            nm_id=sku, date_from=date_from, date_to=max(date_to, moscow_today())
        )
        funnel_details, window_order_sum, window_buyout_sum = _price_funnel_details(
            funnel_rows, price_snapshots
        )
        return FunnelResponseSchema(
            nm_id=sku,
            window_start=date_from,
            window_end=date_to,
            raw_orders=sum(r.order_count for r in funnel_rows),
            totals=compute_funnel_totals(
                funnel_rows, order_sum=window_order_sum, buyout_sum=window_buyout_sum
            ),
            days=funnel_details,
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


def _price_funnel_details(
    funnel_rows: list[SalesFunnelDaily],
    price_snapshots: list[PriceSnapshot],
) -> tuple[list[FunnelDetailRead], float, float]:
    """Build per-day funnel DTOs with price-derived ₽ volumes + their window totals.

    The stored funnel row no longer carries ₽ volumes; each day's «Заказы, ₽» /
    «Выкупы, ₽» are ``count x carry-forward seller price`` (``0.0`` when the SKU
    is unpriced), matching the matrix «Общая» column.

    Args:
        funnel_rows: The SKU's daily funnel rows for the display window.
        price_snapshots: The SKU's price snapshots (any order).

    Returns:
        ``(day_dtos, window_order_sum, window_buyout_sum)``.
    """
    ordered = sorted(price_snapshots, key=lambda s: s.stat_date)
    details: list[FunnelDetailRead] = []
    total_order_sum = total_buyout_sum = 0.0
    for row in funnel_rows:
        seller, _customer = price_for_day(ordered, row.stat_date)
        detail = FunnelDetailRead.model_validate(row)
        if seller is not None:
            detail.order_sum = round(row.order_count * seller, 2)
            detail.buyout_sum = round(row.buyout_count * seller, 2)
        total_order_sum += detail.order_sum
        total_buyout_sum += detail.buyout_sum
        details.append(detail)
    return details, round(total_order_sum, 2), round(total_buyout_sum, 2)


def _compute_baseline(
    funnel_rows: list[SalesFunnelDaily],
    stock_daily_totals: dict[date, int],
) -> BaselineDemandRead:
    """Run the normalization pipeline over a SKU's window.

    Joins each funnel day with that day's total stock so out-of-stock days are
    masked out of the demand baseline. A day with no stock snapshot at all
    (harvest gap) is treated as in-stock — masking requires positive evidence
    of OOS, otherwise gaps would silently deflate ``considered_days``.

    Promo-lift and seasonality factors stay at their neutral ``1.0`` defaults
    until those data sources are integrated.
    """
    points = [
        DailyDemandPoint(
            day=row.stat_date,
            raw_orders=row.order_count,
            total_stock=stock_daily_totals.get(row.stat_date, 1),
        )
        for row in funnel_rows
    ]
    result = compute_baseline_demand(points)
    return BaselineDemandRead(
        baseline_organic_demand=result.baseline_organic_demand,
        oos_days_excluded=result.oos_days_excluded,
        considered_days=result.considered_days,
    )


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
    latest: list[StockSnapshot],
    size_labels: dict[int, str],
    marked_warehouses: list[str],
) -> StockDetail:
    """Build the stock summary + size x warehouse breakdown for a SKU.

    Receives only the most recent snapshot day's rows (the repository filters
    in SQL — stock is a point-in-time snapshot, not a series). Each ``chrt_id``
    is decorated with its human ``tech_size`` from ``size_labels`` (``None``
    when the catalogue has not been synced for that size yet, so old rows keep
    working).

    Args:
        latest: The SKU's rows for its latest snapshot day in the window.
        size_labels: Map of ``chrt_id -> tech_size`` for the SKU's sizes.
        marked_warehouses: The SKU's «Отгрузить»-marked warehouse names.

    Returns:
        A populated :class:`StockDetail` (all zeros/empty when no stock exists).
    """
    if not latest:
        return StockDetail(
            total_quantity=0,
            total_in_way_to_client=0,
            total_in_way_from_client=0,
            marked_warehouses=marked_warehouses,
        )

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
        marked_warehouses=marked_warehouses,
    )
