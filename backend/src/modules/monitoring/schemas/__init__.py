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
    BaselineDemandRead,
    FunnelDetailRead,
    FunnelResponseSchema,
    FunnelTotals,
    compute_funnel_totals,
)
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MATRIX_METRIC_KEYS,
    MatrixBaseState,
    MatrixCellEdit,
    MatrixMetricRow,
    MatrixPreviewRequest,
    MatrixPreviewResponse,
    MatrixSaveRequest,
    MetricsMatrixRead,
    RefreshEnqueuedResponse,
    RefreshStatusResponse,
)
from src.modules.monitoring.schemas.products import (
    SkuLookupItem,
    SkuLookupResponse,
)
from src.modules.monitoring.schemas.stocks import (
    StockCell,
    StockDetail,
    StockSizeTotal,
    WarehouseMarksResponse,
    WarehouseMarkUpdateRequest,
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
    "MATRIX_BUCKETS",
    "MATRIX_METRIC_KEYS",
    "AdMetrics",
    "BaselineDemandRead",
    "CampaignAdvertising",
    "CampaignDailyStat",
    "CatalogIngestionResult",
    "FunnelDetailRead",
    "FunnelResponseSchema",
    "FunnelTotals",
    "IngestionResult",
    "MatrixBaseState",
    "MatrixCellEdit",
    "MatrixMetricRow",
    "MatrixPreviewRequest",
    "MatrixPreviewResponse",
    "MatrixSaveRequest",
    "MetricWindow",
    "MetricsMatrixRead",
    "RefreshEnqueuedResponse",
    "RefreshStatusResponse",
    "SkuDetailResponse",
    "SkuLookupItem",
    "SkuLookupResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
    "StockCell",
    "StockDetail",
    "StockSizeTotal",
    "WarehouseMarkUpdateRequest",
    "WarehouseMarksResponse",
    "compute_ad_metrics",
    "compute_funnel_totals",
]
