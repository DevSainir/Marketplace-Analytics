"""Business-logic layer for the Monitoring module.

Three sub-packages plus one pure module, each with a single responsibility and
**no** direct database access (they collaborate through injected repositories):

* :mod:`~src.modules.monitoring.services.ingestion` —
  :class:`IngestionService` and its per-family units: flatten raw WB payloads
  and persist them via repositories.
* :mod:`~src.modules.monitoring.services.analytics` —
  :class:`AnalyticsService` and its read sub-services: read persisted rows and
  render summary/detail DTOs.
* :mod:`~src.modules.monitoring.services.matrix` — pure builders for the
  day x traffic-bucket metrics matrix (derive, build, edit, overrides).
* :mod:`~src.modules.monitoring.services.normalization` — pure functions
  implementing the baseline-organic-demand cleansing pipeline.

This ``__init__`` is the layer's facade: external consumers (Celery tasks, the
DI wiring, the module contract) import the services from here and are
insulated from the internal package layout.
"""

from src.modules.monitoring.services.analytics import AnalyticsService
from src.modules.monitoring.services.ingestion import IngestionService

__all__ = ["AnalyticsService", "IngestionService"]
