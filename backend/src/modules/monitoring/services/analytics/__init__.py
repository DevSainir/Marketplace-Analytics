"""Read-side analytics package for the Monitoring module.

Composes persisted funnel, advertising, and stock rows (fetched via injected
repositories) with the pure normalization pipeline to produce the summary
listing, detailed view, and cleansed funnel DTOs. It performs **no** SQL and
**no** HTTP — application services only.

One responsibility per module:

* :mod:`~src.modules.monitoring.services.analytics.window` — analysis-window
  resolution and validation.
* :mod:`~src.modules.monitoring.services.analytics.presenters` — pure DTO
  builders shared by the read services.
* :mod:`~src.modules.monitoring.services.analytics.summary` — the per-SKU
  summary listing and the vendor-code lookup.
* :mod:`~src.modules.monitoring.services.analytics.detail` — the single-SKU
  detailed view, the raw funnel read, and the shared matrix fact fetch.
* :mod:`~src.modules.monitoring.services.analytics.matrix_editing` — matrix
  edit preview and override persistence.
* :mod:`~src.modules.monitoring.services.analytics.pins` — the global
  pinned-SKU chips.
* :mod:`~src.modules.monitoring.services.analytics.annotations` — per-day
  notes and «Действия» answers.
* :mod:`~src.modules.monitoring.services.analytics.stock_view` — exact-day
  stock breakdowns and warehouse marks.
* :mod:`~src.modules.monitoring.services.analytics.service` — the
  :class:`AnalyticsService` facade the presentation layer depends on.

This ``__init__`` is the package facade: the DI wiring, contract, and routers
keep importing :class:`AnalyticsService` exactly as they did from the former
flat ``services/analytics.py`` module.
"""

from src.modules.monitoring.services.analytics.annotations import DayAnnotationAnalytics
from src.modules.monitoring.services.analytics.detail import DetailAnalytics
from src.modules.monitoring.services.analytics.matrix_editing import MatrixEditingAnalytics
from src.modules.monitoring.services.analytics.pins import PinnedSkuAnalytics
from src.modules.monitoring.services.analytics.service import AnalyticsService
from src.modules.monitoring.services.analytics.stock_view import StockViewAnalytics
from src.modules.monitoring.services.analytics.summary import SummaryAnalytics
from src.modules.monitoring.services.analytics.window import resolve_window

__all__ = [
    "AnalyticsService",
    "DayAnnotationAnalytics",
    "DetailAnalytics",
    "MatrixEditingAnalytics",
    "PinnedSkuAnalytics",
    "StockViewAnalytics",
    "SummaryAnalytics",
    "resolve_window",
]
