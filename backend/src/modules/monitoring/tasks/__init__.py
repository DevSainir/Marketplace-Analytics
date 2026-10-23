"""Celery background tasks for harvesting WildBerries data.

Celery task entrypoints are synchronous, but the entire I/O stack (HTTP + DB) is
async. Each task therefore drives an async coroutine to completion via
``asyncio.run`` and manages its own :class:`AsyncSession` — it cannot use the
FastAPI request-scoped ``get_db`` dependency, so it composes the same
repository/service graph manually.

One responsibility per module:

* :mod:`~src.modules.monitoring.tasks.common` — the shared retry policy and
  the resilient-gather helper.
* :mod:`~src.modules.monitoring.tasks.planning` — pure selection of the
  campaigns / search pairs a harvest should pull.
* :mod:`~src.modules.monitoring.tasks.harvest` — the SKU-window harvest core:
  fetch, flatten and persist, in one transaction. Driven by both tasks below.
* :mod:`~src.modules.monitoring.tasks.refresh` — the interactive
  ``monitoring.harvest_sku_window`` task ("Refresh").
* :mod:`~src.modules.monitoring.tasks.discovery` — workspace SKU discovery:
  the nightly ``monitoring.harvest_all`` task and its single-tenant
  ``monitoring.discover_workspace`` counterpart.
* :mod:`~src.modules.monitoring.tasks.cohorts` — the
  ``monitoring.refresh_buyout_cohorts`` pass over maturing order-date cohorts.
* :mod:`~src.modules.monitoring.tasks.day_headers` — the
  ``monitoring.carry_day_headers`` day-boundary carry.
* :mod:`~src.modules.monitoring.tasks.reviews` — the
  ``monitoring.snapshot_reviews`` daily rating and review history.

This ``__init__`` is the package facade Celery's ``autodiscover_tasks`` imports
(it looks for ``src.modules.monitoring.tasks``): importing it imports every
task module, so all tasks register under their unchanged explicit
``monitoring.*`` names, and external consumers (the routers' "Refresh"
endpoint) keep importing the task callables from here.
"""

from src.modules.monitoring.tasks.backfill import (
    backfill_advertising,
    backfill_catalogue,
    backfill_funnel,
)
from src.modules.monitoring.tasks.cohorts import COHORT_REFRESH_DAYS, refresh_buyout_cohorts
from src.modules.monitoring.tasks.day_headers import carry_day_headers
from src.modules.monitoring.tasks.discovery import discover_workspace, harvest_all
from src.modules.monitoring.tasks.price_topup import top_up_customer_prices
from src.modules.monitoring.tasks.refresh import harvest_sku_window
from src.modules.monitoring.tasks.reviews import snapshot_reviews

__all__ = [
    "COHORT_REFRESH_DAYS",
    "backfill_advertising",
    "backfill_catalogue",
    "backfill_funnel",
    "carry_day_headers",
    "discover_workspace",
    "harvest_all",
    "harvest_sku_window",
    "refresh_buyout_cohorts",
    "snapshot_reviews",
    "top_up_customer_prices",
]
