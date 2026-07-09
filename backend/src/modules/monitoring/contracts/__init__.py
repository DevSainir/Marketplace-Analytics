"""Public contract for the Monitoring module.

The stable, import-safe surface other modules may consume. Per the "no
horizontal imports" rule, external modules import monitoring capabilities from
here only — never from ``services``/``repos``/``models`` internals.

Currently the module is a leaf (nothing depends on it yet), so the contract
re-exports the read DTOs and the service type that future consumers would use.
"""

from src.modules.monitoring.schemas import (
    SkuDetailResponse,
    SkuSummaryItem,
    SkuSummaryListResponse,
)
from src.modules.monitoring.services import AnalyticsService

__all__ = [
    "AnalyticsService",
    "SkuDetailResponse",
    "SkuSummaryItem",
    "SkuSummaryListResponse",
]
