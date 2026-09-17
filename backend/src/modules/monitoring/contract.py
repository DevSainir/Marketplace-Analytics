"""Public contract for the Monitoring module.

The stable, import-safe surface other modules may consume. Per the "no
horizontal imports" rule, external modules import monitoring capabilities from
here only — never from ``services``/``repos``/``models`` internals.

The read DTOs and the service type are re-exported for future consumers; the
``load_*``/``*_coverage``/``stock_day_span`` loaders are consumed today by the
finreports P&L, which needs per-SKU orders and advertising spend the settlement
report does not carry, and by its «Баланс по товарным остаткам» table, which
prices the stock still sitting in the warehouses.
"""

from src.modules.monitoring.schemas import (
    SkuDetailResponse,
    SkuSummaryItem,
    SkuSummaryListResponse,
)
from src.modules.monitoring.services import (
    BUYOUT_LAG_END_DAYS,
    BUYOUT_LAG_START_DAYS,
    AdDay,
    AdSpendDay,
    AnalyticsService,
    OrderDay,
    WarehouseStock,
    WorkspaceCard,
    ad_bonus_coverage,
    ad_bonus_currencies,
    ad_bonus_unknown_types,
    ad_coverage,
    funnel_coverage,
    load_ad_bonus_by_nm,
    load_ad_days,
    load_ad_days_for_nm,
    load_ad_spend_by_nm,
    load_campaign_ids_for_workspace,
    load_card_photos,
    load_order_days,
    load_orders_by_nm,
    load_stock_by_warehouse,
    load_vendor_codes,
    load_workspace_card,
    search_workspace_cards,
    stock_day_span,
)

__all__ = [
    "BUYOUT_LAG_END_DAYS",
    "BUYOUT_LAG_START_DAYS",
    "AdDay",
    "AdSpendDay",
    "AnalyticsService",
    "OrderDay",
    "SkuDetailResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
    "WarehouseStock",
    "WorkspaceCard",
    "ad_bonus_coverage",
    "ad_bonus_currencies",
    "ad_bonus_unknown_types",
    "ad_coverage",
    "funnel_coverage",
    "load_ad_bonus_by_nm",
    "load_ad_days",
    "load_ad_days_for_nm",
    "load_ad_spend_by_nm",
    "load_campaign_ids_for_workspace",
    "load_card_photos",
    "load_order_days",
    "load_orders_by_nm",
    "load_stock_by_warehouse",
    "load_vendor_codes",
    "load_workspace_card",
    "search_workspace_cards",
    "stock_day_span",
]
