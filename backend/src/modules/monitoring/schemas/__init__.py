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
from src.modules.monitoring.schemas.aggregate import AggregateChartsResponse
from src.modules.monitoring.schemas.comment import (
    COMMENT_MAX_LENGTH,
    HEADER_MAX_LENGTH,
    CommentUpdateRequest,
    DayCommentResponse,
    DayNote,
)
from src.modules.monitoring.schemas.day_actions import (
    DayActionResponse,
    DayActionState,
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
from src.modules.monitoring.schemas.pins import (
    COLOR_PATTERN,
    PinColorUpdateRequest,
    PinnedSkuItem,
    PinnedSkusResponse,
    PinReorderRequest,
    PinUpdateRequest,
)
from src.modules.monitoring.schemas.products import (
    SkuLookupItem,
    SkuLookupResponse,
)
from src.modules.monitoring.schemas.stocks import (
    StockCell,
    StockDayResponse,
    StockDetail,
    StockRangeResponse,
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
    "COLOR_PATTERN",
    "COMMENT_MAX_LENGTH",
    "HEADER_MAX_LENGTH",
    "MATRIX_BUCKETS",
    "MATRIX_METRIC_KEYS",
    "AdMetrics",
    "AggregateChartsResponse",
    "BaselineDemandRead",
    "CampaignAdvertising",
    "CampaignDailyStat",
    "CatalogIngestionResult",
    "CommentUpdateRequest",
    "DayActionResponse",
    "DayActionState",
    "DayCommentResponse",
    "DayNote",
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
    "PinColorUpdateRequest",
    "PinReorderRequest",
    "PinUpdateRequest",
    "PinnedSkuItem",
    "PinnedSkusResponse",
    "RefreshEnqueuedResponse",
    "RefreshStatusResponse",
    "SkuDetailResponse",
    "SkuLookupItem",
    "SkuLookupResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
    "StockCell",
    "StockDayResponse",
    "StockDetail",
    "StockRangeResponse",
    "StockSizeTotal",
    "compute_ad_metrics",
    "compute_funnel_totals",
]
