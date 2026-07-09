"""Business-logic layer for the Monitoring module.

Three services, each with a single responsibility and **no** direct database
access (they collaborate through injected repositories):

* :class:`~src.modules.monitoring.services.ingestion.IngestionService` —
  flattens raw WB payloads and persists them via repositories.
* :class:`~src.modules.monitoring.services.analytics.AnalyticsService` —
  reads persisted rows and renders summary/detail DTOs.
* :mod:`~src.modules.monitoring.services.normalization` — pure functions
  implementing the baseline-organic-demand cleansing pipeline.
"""

from src.modules.monitoring.services.analytics import AnalyticsService
from src.modules.monitoring.services.ingestion import IngestionService

__all__ = ["AnalyticsService", "IngestionService"]
