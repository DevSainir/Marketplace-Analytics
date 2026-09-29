"""Every metric this service exports, defined in one place (register P2.1).

One module holds all the definitions, and the call sites only ever *record*.
That is the arrangement that keeps a metric honest: a counter declared next to
the code that increments it acquires a label whenever that code grows a new
case, and nobody notices until a dashboard has forty thousand series and
Prometheus is the largest process on the box.

Cardinality is the whole discipline here
----------------------------------------
A Prometheus series is one time series per unique label combination, held in
memory for as long as it is fresh. So the rule every metric below obeys is that
**each label has a small, closed set of values known before the code runs**:
a WB surface name, a request path template, an HTTP status, a task name, a
harvest source. What is deliberately absent from every label list is the
tenant — `workspace_id` and `organization_id` are unbounded by construction
(they grow with the customer list) and would multiply every series by the
number of sellers.

That is not only a memory argument. Per-tenant metrics would put customer
volumes in a store with weaker access control than the database they came from,
and `/metrics` has no tenancy check because it has no tenant. The per-tenant
question — "whose harvest failed" — is answered by the logs, which carry
`workspace_id` on every line and are scoped by the same guard as everything
else. Metrics answer "is the system healthy", logs answer "for whom".

Multiprocess
------------
The API is one process and needs nothing special. The Celery worker is a
prefork pool: the process that serves a scrape is not the process that counted
the harvest, so counters have to live in mmap files both can see
(`PROMETHEUS_MULTIPROC_DIR`). Counters and histograms aggregate by summing,
which is correct without any configuration. Gauges cannot — four processes
each holding "the queue is 12 long" must not sum to 48 — so every gauge here
declares an explicit `multiprocess_mode`, and choosing it is a real decision
rather than boilerplate. See each one.


The package is split by subject — `wildberries`, `celery`, `harvest`,
`security`, `infrastructure` — and every name is re-exported here, so
`from src.core.observability.metrics import HARVEST_ROWS` keeps working and no
call site has to know which file a metric lives in. The split is the 500-line
ceiling doing its job: one flat file had grown past it, and "which subject" is
the only division that does not cut a metric off from the paragraph explaining
why it is shaped the way it is.
"""

from __future__ import annotations

from src.core.observability.metrics.celery import (
    CELERY_QUEUE_LENGTH,
    CELERY_TASK_DURATION,
    CELERY_TASK_MEMORY_GROWTH,
    CELERY_TASK_PEAK_MEMORY,
    CELERY_TASK_START_MEMORY,
    CELERY_TASKS,
    CELERY_WORKER_LOST,
)
from src.core.observability.metrics.harvest import (
    BACKFILL_LANE_FAILURES,
    BACKFILL_LANE_RESTARTS,
    BACKFILL_LANES_STALLED,
    HARVEST_DURATION,
    HARVEST_PARTIAL,
    HARVEST_ROWS,
    SETTLEMENT_GAP_DAYS,
    SETTLEMENT_PAYOUT_DIVERGENCE,
)
from src.core.observability.metrics.infrastructure import (
    APP_INFO,
    DEPENDENCY_PROBE_DURATION,
    DEPENDENCY_UP,
    POSTGRES_POOL_FREE,
    POSTGRES_POOL_OVERFLOW,
    POSTGRES_POOL_USED,
    POSTGRES_STATS_RESET,
    set_app_info,
)
from src.core.observability.metrics.security import (
    SECURITY_AUTH_FAILURES,
    SECURITY_DEGRADED_CONTROLS,
    SECURITY_RLS_VIOLATIONS,
)
from src.core.observability.metrics.wildberries import (
    WB_API_DURATION,
    WB_API_REQUESTS,
    WB_RATE_LIMIT_BLOCK,
    WB_RATE_LIMIT_REMAINING,
    WB_RATE_LIMIT_WAIT,
)

__all__ = [
    "APP_INFO",
    "BACKFILL_LANES_STALLED",
    "BACKFILL_LANE_FAILURES",
    "BACKFILL_LANE_RESTARTS",
    "CELERY_QUEUE_LENGTH",
    "CELERY_TASKS",
    "CELERY_TASK_DURATION",
    "CELERY_TASK_MEMORY_GROWTH",
    "CELERY_TASK_PEAK_MEMORY",
    "CELERY_TASK_START_MEMORY",
    "CELERY_WORKER_LOST",
    "DEPENDENCY_PROBE_DURATION",
    "DEPENDENCY_UP",
    "HARVEST_DURATION",
    "HARVEST_PARTIAL",
    "HARVEST_ROWS",
    "POSTGRES_POOL_FREE",
    "POSTGRES_POOL_OVERFLOW",
    "POSTGRES_POOL_USED",
    "POSTGRES_STATS_RESET",
    "SECURITY_AUTH_FAILURES",
    "SECURITY_DEGRADED_CONTROLS",
    "SECURITY_RLS_VIOLATIONS",
    "SETTLEMENT_GAP_DAYS",
    "SETTLEMENT_PAYOUT_DIVERGENCE",
    "WB_API_DURATION",
    "WB_API_REQUESTS",
    "WB_RATE_LIMIT_BLOCK",
    "WB_RATE_LIMIT_REMAINING",
    "WB_RATE_LIMIT_WAIT",
    "set_app_info",
]
