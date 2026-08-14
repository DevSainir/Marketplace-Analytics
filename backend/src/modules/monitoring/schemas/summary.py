"""Aggregate summary (listing) and detailed-view response DTOs.

The Monitoring API serves data two ways:
    * **Summary listing** — one compact :class:`SkuSummaryItem` per SKU for
      dashboards/tables.
    * **Detailed view** — a :class:`SkuDetailResponse` combining funnel,
      advertising, and stock breakdowns for a single SKU.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from src.modules.monitoring.schemas.advertising import CampaignAdvertising
from src.modules.monitoring.schemas.comment import DayNote
from src.modules.monitoring.schemas.day_actions import DayActionState
from src.modules.monitoring.schemas.funnel import (
    BaselineDemandRead,
    FunnelDetailRead,
    FunnelTotals,
)
from src.modules.monitoring.schemas.matrix import MatrixBaseState, MetricsMatrixRead
from src.modules.monitoring.schemas.stocks import StockDetail


class MetricWindow(BaseModel):
    """The inclusive date window an aggregate was computed over."""

    start: date
    end: date


class SkuSummaryItem(BaseModel):
    """Compact per-SKU rollup for the summary listing endpoint.

    Funnel metrics are window totals (summed across days); the conversion ratios
    are recomputed from those totals, not averaged. Advertising and stock keep
    their existing rollups.

    **Two attribution bases meet here, on purpose.** The funnel counts
    (``total_open_count`` … ``total_orders``) are ORDER-date facts from WB's
    analytics feed. The buyout/return figures are SALE-date facts from the
    Statistics ``supplier/sales`` records — real per-item money, which is what
    makes ``total_buyout_sum`` match the manager's Excel «Выкупы, ₽».

    Consequently there is deliberately **no «Процент выкупа» here**. That metric
    is ``buyouts / (buyouts + refusals-at-pickup)`` over a LAGGED cohort window
    and lives on the SKU matrix (``buyout_percent``). It cannot be answered for
    this endpoint's arbitrary window: refusals never become sale records, and
    ``sales_funnel_daily.cancel_count`` only covers the last 22 days while this
    window defaults to 30 and allows 366. Do not add a buyout-flavoured ratio
    here from ``sale_record`` — its denominator (buyouts + RETURNS) is a
    different, far smaller population, which is exactly how the old
    ``buyout_conversion`` came to report 90% against WB's 30%.
    """

    nm_id: int = Field(description="WB SKU identifier.")
    vendor_code: str | None = Field(
        default=None, description="Seller article code (WB 'Артикул продавца')."
    )
    title: str | None = Field(default=None, description="Product card title.")
    # --- Organic funnel totals over the window (ORDER-date) ---
    total_open_count: int = Field(description="Total card opens over the window.")
    total_cart_count: int = Field(description="Total add-to-cart events.")
    total_orders: int = Field(description="Total orders over the window.")
    total_order_sum: float = Field(description="Total ordered value in rubles.")
    # --- Sale/return records over the window (SALE-date) ---
    total_buyout_count: int = Field(
        description="Buyouts RECORDED in the window (sale-date, not the window's orders)."
    )
    total_buyout_sum: float = Field(description="Total buyout value in rubles (sale-date).")
    total_return_count: int = Field(
        description=(
            "Post-purchase returns recorded in the window (sale-date) — a buyer sending "
            "an item back AFTER buying it. NOT a refusal at pickup (WB `cancelCount`), "
            "which never becomes a sale record and drives «Процент выкупа» instead."
        )
    )
    total_add_to_wishlist: int = Field(description="Total add-to-favourites events.")
    cart_conversion: float = Field(description="open -> cart (%), from totals.")
    order_conversion: float = Field(description="cart -> order (%), from totals.")
    # --- Advertising + stock rollups ---
    total_ad_spend: float = Field(description="Advertising expenses over the window.")
    total_ad_clicks: int = Field(description="Advertising clicks over the window.")
    latest_stock: int = Field(description="Most recent total remaining stock.")
    is_out_of_stock: bool = Field(description="True when latest total stock is zero.")


class SkuSummaryListResponse(BaseModel):
    """Paginated envelope for the summary listing."""

    window: MetricWindow
    count: int = Field(description="Number of SKU items returned on this page.")
    total: int = Field(description="Total SKUs with data in the window (all pages).")
    limit: int = Field(description="Requested page size.")
    offset: int = Field(description="Requested page offset.")
    items: list[SkuSummaryItem] = Field(default_factory=list)


class SkuDetailResponse(BaseModel):
    """Full detailed view for a single SKU across all metric families.

    ``advertising`` is grouped per campaign (each with its own totals + daily
    breakdown and campaign status); ``stock`` carries the summary total plus the
    size x warehouse breakdown.
    """

    nm_id: int
    vendor_code: str | None = Field(
        default=None, description="Seller article code (WB 'Артикул продавца')."
    )
    title: str | None = Field(default=None, description="Product card title.")
    comments: dict[date, DayNote] = Field(
        default_factory=dict,
        description="Per-day notes (comment + header), keyed by day; days "
        "without a note are absent. Values are stored facts — the header's "
        "day-to-day carry is materialized at the day boundary, not derived "
        "here.",
    )
    day_actions: dict[date, DayActionState] = Field(
        default_factory=dict,
        description="Per-day manager action rows («Действия»: РК toggles + "
        "budgets, price change), keyed by day; untouched days are absent.",
    )
    window: MetricWindow
    funnel: list[FunnelDetailRead] = Field(default_factory=list)
    funnel_totals: FunnelTotals = Field(
        description="Window-total funnel metrics summed across the daily rows."
    )
    baseline_demand: BaselineDemandRead = Field(
        description="Cleansed baseline organic demand (OOS days masked out)."
    )
    advertising: list[CampaignAdvertising] = Field(default_factory=list)
    matrix: MetricsMatrixRead = Field(
        description="Precomputed day x traffic-bucket metrics matrix (the "
        "monitoring table renders it verbatim — no frontend math)."
    )
    matrix_base: MatrixBaseState = Field(
        description="Editable input working copy behind the matrix (with any "
        "saved manual overrides applied) — the frontend edits this."
    )
    stock: StockDetail


class IngestionResult(BaseModel):
    """Summary of a harvesting run, returned by ingestion service methods."""

    funnel_rows: int = Field(default=0, description="Funnel rows upserted.")
    advertising_rows: int = Field(default=0, description="Advertising rows upserted.")
    search_zone_rows: int = Field(default=0, description="Search-zone advertising rows upserted.")
    search_cluster_rows: int = Field(
        default=0, description="Per-search-cluster advertising rows upserted."
    )
    stock_rows: int = Field(default=0, description="Stock rows upserted.")
    price_rows: int = Field(default=0, description="Price snapshot rows upserted.")
    sales_rows: int = Field(default=0, description="Per-item sale/return records upserted.")


class CatalogIngestionResult(BaseModel):
    """Summary of a product-catalogue sync from the Content API."""

    product_card_rows: int = Field(
        default=0, description="Product-card (vendor code) rows upserted."
    )
    product_size_rows: int = Field(default=0, description="Product-size (label) rows upserted.")
