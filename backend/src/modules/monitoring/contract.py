"""Public contract for the Monitoring module.

The stable, import-safe surface other modules may consume. Per the "no
horizontal imports" rule, external modules import monitoring capabilities from
here only — never from ``services``/``repos``/``models`` internals.

The read DTOs and the service type are re-exported for future consumers; the
``load_*``/``*_coverage`` loaders are consumed today by the finreports P&L,
which needs per-SKU orders and advertising spend the settlement report does not
carry.
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
]
