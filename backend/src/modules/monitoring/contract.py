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
    AnalyticsService,
    ad_coverage,
    funnel_coverage,
    load_ad_spend_by_nm,
    load_orders_by_nm,
    load_stock_by_warehouse,
    load_vendor_codes,
    stock_day_span,
)

__all__ = [
    "AnalyticsService",
    "SkuDetailResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
    "ad_coverage",
    "funnel_coverage",
    "load_ad_spend_by_nm",
    "load_orders_by_nm",
    "load_stock_by_warehouse",
    "load_vendor_codes",
    "stock_day_span",
]
