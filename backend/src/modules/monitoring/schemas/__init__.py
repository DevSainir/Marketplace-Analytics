"""Pydantic DTOs for the Monitoring presentation boundary.

Re-exports every response/request schema so routers and the contract can import
from ``src.modules.monitoring.schemas`` directly.
"""

from src.modules.monitoring.schemas.advertising import (
    AdMetrics,
    CampaignAdvertising,
    CampaignDailyStat,
    compute_ad_metrics,
)
from src.modules.monitoring.schemas.funnel import (
    FunnelDetailRead,
    FunnelResponseSchema,
    FunnelTotals,
    compute_funnel_totals,
)
from src.modules.monitoring.schemas.products import (
    SkuLookupItem,
    SkuLookupResponse,
)
from src.modules.monitoring.schemas.stocks import (
    StockCell,
    StockDetail,
    StockSizeTotal,
)
from src.modules.monitoring.schemas.summary import (
    CatalogIngestionResult,
    IngestionResult,
    MetricWindow,
    SkuDetailResponse,
    SkuSummaryItem,
    SkuSummaryListResponse,
)

__all__ = [
    "AdMetrics",
    "CampaignAdvertising",
    "CampaignDailyStat",
    "CatalogIngestionResult",
    "FunnelDetailRead",
    "FunnelResponseSchema",
    "FunnelTotals",
    "IngestionResult",
    "MetricWindow",
    "SkuDetailResponse",
    "SkuLookupItem",
    "SkuLookupResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
    "StockCell",
    "StockDetail",
    "StockSizeTotal",
    "compute_ad_metrics",
    "compute_funnel_totals",
]
