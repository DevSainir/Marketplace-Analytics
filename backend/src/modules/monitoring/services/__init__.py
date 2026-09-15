"""Business-logic layer for the Monitoring module.

Three sub-packages plus one pure module, each with a single responsibility and
**no** direct database access (they collaborate through injected repositories):

* :mod:`~src.modules.monitoring.services.ingestion` —
  :class:`IngestionService` and its per-family units: flatten raw WB payloads
  and persist them via repositories.
* :mod:`~src.modules.monitoring.services.analytics` —
  :class:`AnalyticsService` and its read sub-services: read persisted rows and
  render summary/detail DTOs.
* :mod:`~src.modules.monitoring.services.cards` — the catalogue-card loaders
  the A/B-tests article picker resolves and ranks its options with.
* :mod:`~src.modules.monitoring.services.matrix` — pure builders for the
  day x traffic-bucket metrics matrix (derive, build, edit, overrides).
* :mod:`~src.modules.monitoring.services.normalization` — pure functions
  implementing the baseline-organic-demand cleansing pipeline.
* :mod:`~src.modules.monitoring.services.refresh_tracking` — the Redis
  binding that makes an interactive refresh task's status readable only by
  the workspace that enqueued it.

This ``__init__`` is the layer's facade: external consumers (Celery tasks, the
DI wiring, the module contract) import the services from here and are
insulated from the internal package layout.
"""

from src.modules.monitoring.services.ad_bonus import (
    ad_bonus_coverage,
    ad_bonus_currencies,
    ad_bonus_unknown_types,
    load_ad_bonus_by_nm,
)
from src.modules.monitoring.services.analytics import (
    AnalyticsService,
    ClusterAnalytics,
)
from src.modules.monitoring.services.cards import (
    WorkspaceCard,
    load_workspace_card,
    search_workspace_cards,
)
from src.modules.monitoring.services.exports import (
    AdDay,
    WarehouseStock,
    ad_coverage,
    funnel_coverage,
    load_ad_days_for_nm,
    load_ad_spend_by_nm,
    load_campaign_ids_for_workspace,
    load_card_photos,
    load_orders_by_nm,
    load_stock_by_warehouse,
    load_vendor_codes,
    stock_day_span,
)
from src.modules.monitoring.services.ingestion import IngestionService
from src.modules.monitoring.services.refresh_tracking import (
    bind_task_to_workspace,
    claim_cohort_pass,
    remember_running_task,
    spend_refresh_budget,
    task_already_running,
    task_belongs_to_workspace,
)

__all__ = [
    "AdDay",
    "AnalyticsService",
    "ClusterAnalytics",
    "IngestionService",
    "WarehouseStock",
    "WorkspaceCard",
    "ad_bonus_coverage",
    "ad_bonus_currencies",
    "ad_bonus_unknown_types",
    "ad_coverage",
    "bind_task_to_workspace",
    "claim_cohort_pass",
    "funnel_coverage",
    "load_ad_bonus_by_nm",
    "load_ad_days_for_nm",
    "load_ad_spend_by_nm",
    "load_campaign_ids_for_workspace",
    "load_card_photos",
    "load_orders_by_nm",
    "load_stock_by_warehouse",
    "load_vendor_codes",
    "load_workspace_card",
    "remember_running_task",
    "search_workspace_cards",
    "spend_refresh_budget",
    "stock_day_span",
    "task_already_running",
    "task_belongs_to_workspace",
]
