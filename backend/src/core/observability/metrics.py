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
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------- #
# WildBerries — the dependency that fails most, and least visibly.
# --------------------------------------------------------------------------- #

#: Every WB call, by surface, endpoint and outcome.
#:
#: `status` carries the HTTP code as a string, or one of the two non-HTTP
#: outcomes: `transport_error` (the connection failed or timed out) and
#: `rate_blocked` (our own gate refused to send, because WB's stated wait
#: exceeded the queue cap). Those two are counted here rather than dropped
#: because they are how WB actually fails — an over-budget analytics request
#: is answered with a held-open connection, not a 429 (measured 2026-07-30),
#: and a failure that produces no status would otherwise be invisible in the
#: one metric that is supposed to show WB's health.
WB_API_REQUESTS: Final[Counter] = Counter(
    "wb_api_requests_total",
    "WildBerries API requests by surface, endpoint and outcome.",
    ["surface", "endpoint", "status"],
)

#: How long WB took to answer, per attempt. Buckets stretch to 120s on
#: purpose: the interesting part of this distribution is the tail, where a
#: request sits behind an empty bucket until a read timeout fires, and default
#: buckets (top out at 10s) would put every one of those in `+Inf` and show
#: nothing.
WB_API_DURATION: Final[Histogram] = Histogram(
    "wb_api_request_duration_seconds",
    "Round-trip time of one WildBerries API attempt.",
    ["surface", "endpoint"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0),
)

#: What WB last said was left in this endpoint's bucket
#: (`x-ratelimit-remaining`). The leading indicator for the whole harvest: it
#: reaches zero before anything fails, so an alert on it fires while there is
#: still time to do something, rather than after a night's data is missing.
#:
#: `livemostrecent` because the truthful answer is "what the most recent
#: observation from a process that is still alive said" — summing across
#: workers would invent budget WB never granted, and `max` would report the
#: luckiest worker's view right up to the moment everything stalls.
WB_RATE_LIMIT_REMAINING: Final[Gauge] = Gauge(
    "wb_rate_limit_quota_remaining",
    "Tokens WB reported remaining in this endpoint's bucket.",
    ["surface", "endpoint"],
    multiprocess_mode="livemostrecent",
)

#: Seconds spent waiting for a rate token before sending. Rising pacing
#: pressure is what a harvest that is about to overrun its window looks like an
#: hour before it does.
WB_RATE_LIMIT_WAIT: Final[Counter] = Counter(
    "wb_rate_limit_wait_seconds_total",
    "Cumulative seconds spent waiting on the client-side WB rate gate.",
    ["surface", "endpoint"],
)

# --------------------------------------------------------------------------- #
# Celery — the half of this service with no user watching it.
# --------------------------------------------------------------------------- #

#: Messages waiting in a queue, sampled at scrape time by reading Redis
#: directly (see `collectors.py`). Not incremented by anything: a queue's
#: length is a fact about Redis, and deriving it from enqueue/dequeue counters
#: is how a metric drifts from reality after one lost message.
#:
#: `livemostrecent` for the same reason as the WB budget — every process that
#: samples it reads the same Redis key, so summing would multiply one queue by
#: the number of workers.
CELERY_QUEUE_LENGTH: Final[Gauge] = Gauge(
    "celery_queue_length",
    "Messages waiting in a Celery queue.",
    ["queue_name"],
    multiprocess_mode="livemostrecent",
)

#: Task outcomes. `state` is one of `success`, `failure`, `retry`, `revoked`,
#: `soft_timeout` — a closed set from Celery's own signals.
CELERY_TASKS: Final[Counter] = Counter(
    "celery_tasks_total",
    "Celery task executions by name and final state.",
    ["task_name", "state"],
)

#: End-to-end task runtime. The top bucket is 3600s because that is the soft
#: time limit (`src.core.celery_app`), so the last bucket boundary is exactly
#: the line a task is killed for crossing — which makes "approaching the limit"
#: a thing the histogram can actually show.
CELERY_TASK_DURATION: Final[Histogram] = Histogram(
    "celery_task_duration_seconds",
    "Wall-clock duration of one Celery task execution.",
    ["task_name"],
    buckets=(0.5, 1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 1800.0, 3600.0),
)

# --------------------------------------------------------------------------- #
# Harvest — the business outcome, not the transport.
# --------------------------------------------------------------------------- #

#: How long one harvest took, by kind and outcome. Separate from
#: `celery_task_duration_seconds` because a harvest is not a task: one task
#: harvests many workspaces, and a partial harvest (some sources failed, the
#: task succeeded) is the outcome this service produces most often and the one
#: a task-level metric cannot express.
HARVEST_DURATION: Final[Histogram] = Histogram(
    "harvest_duration_seconds",
    "Duration of one harvest run, by kind and outcome.",
    ["harvest", "outcome"],
    buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 180.0, 600.0, 1800.0, 3600.0),
)

#: Rows actually written, by harvest and source. The metric that distinguishes
#: "the harvest succeeded" from "the harvest did anything" — and this codebase
#: has already shipped the gap between those two: after the Redis pool leak,
#: every run reported success with `funnel_rows: 0` for days
#: (see `src.core.tasks.run_task`). A counter that flatlines while its task
#: keeps succeeding is exactly that failure, made alertable.
HARVEST_ROWS: Final[Counter] = Counter(
    "harvest_rows_processed_total",
    "Rows ingested by a harvest, by kind and source.",
    ["harvest", "source"],
)

#: Harvests that finished with at least one source missing. A tolerated
#: partial is a design decision (a failed source must not lose the rest of the
#: run), which is precisely why it needs a counter: without one, the tolerance
#: is indistinguishable from the absence of a problem.
HARVEST_PARTIAL: Final[Counter] = Counter(
    "harvest_partial_total",
    "Harvests that completed with one or more sources unavailable.",
    ["harvest", "source"],
)

# --------------------------------------------------------------------------- #
# Security — controls, counted where they fire.
# --------------------------------------------------------------------------- #

#: A query that reached a row-level-security-protected table without a tenant
#: bound, and was refused by PostgreSQL (register P2.5).
#:
#: **This should be flat at zero forever, and that is what makes it worth
#: exporting.** The policies fail closed: an unbound query raises rather than
#: returning nothing, precisely so the failure is unmissable. This counter is
#: what makes it unmissable *without a person reading logs* — one increment
#: means a code path is reaching tenant data without going through the tenancy
#: choke point, which is the exact defect RLS was installed to catch.
#: The label is ``reason``, not ``table``, and the difference was forced by
#: what PostgreSQL actually reports. The unbound-tenant failure is SQLSTATE
#: 42704 — "unrecognized configuration parameter ``app.workspace_id``" — which
#: names no relation, so a ``table`` label would read ``unknown`` on every
#: single increment and be worse than no label at all. ``reason`` separates the
#: two failures that ARE distinguishable and that mean different things:
#: ``tenant_unset`` is a code path that missed the tenancy choke point, and
#: ``policy_denied`` is one that bound the wrong tenant.
SECURITY_RLS_VIOLATIONS: Final[Counter] = Counter(
    "security_rls_violations_total",
    "Queries refused by row-level security, by why they were refused.",
    ["reason"],
)

#: Rejected authentication attempts, by why. `reason` is a closed set from the
#: auth dependency: `bad_credentials`, `rate_limited`, `backoff`,
#: `revoked_session`, `expired_token`, `invalid_token`.
#:
#: The rate at which this rises is the credential-stuffing signal P1.5's
#: backoff was built for and P2.2 named as an alerting gap. No account, address
#: or address hash is a label — the count is the alert, the identity is in the
#: logs.
SECURITY_AUTH_FAILURES: Final[Counter] = Counter(
    "security_auth_failures_total",
    "Authentication attempts refused, by reason.",
    ["reason"],
)

#: Controls currently reporting degraded (`src.core.degradation`). P1.2 built
#: the ledger and the alertable events; this is the half that lets a rule fire
#: on "the auth rate limiter and session revocation went down together"
#: without anything parsing a log line.
#:
#: `livemax` rather than `livemostrecent`: a control is degraded if ANY live
#: process sees it degraded, and the dangerous rounding is the one that reports
#: healthy because the process asked happened to be fine.
SECURITY_DEGRADED_CONTROLS: Final[Gauge] = Gauge(
    "security_degraded_controls",
    "1 while a security control is running in its degraded fallback mode.",
    ["control"],
    multiprocess_mode="livemax",
)

# --------------------------------------------------------------------------- #
# Infrastructure — the two pools and the two dependencies.
# --------------------------------------------------------------------------- #

#: Connections checked OUT of the SQLAlchemy pool. Pool exhaustion is a
#: documented incident here, not a hypothetical: leaked `idle in transaction`
#: connections held every slot for 22 hours, which is what put the
#: `idle_in_transaction_session_timeout` backstop in `src.core.database`. This
#: is the metric that would have shown it on the first hour.
#:
#: `livesum` across processes: each worker has its own pool, and the total in
#: use is genuinely the sum — unlike a queue length, which is one shared fact.
POSTGRES_POOL_USED: Final[Gauge] = Gauge(
    "postgres_pool_connections_used",
    "Connections currently checked out of the SQLAlchemy pool.",
    multiprocess_mode="livesum",
)

#: Connections sitting idle in the pool, ready to be handed out. Read
#: alongside `_used`: both low means quiet, used-high/free-zero means the next
#: request queues, and that is the shape of the outage above.
POSTGRES_POOL_FREE: Final[Gauge] = Gauge(
    "postgres_pool_connections_free",
    "Idle connections available in the SQLAlchemy pool.",
    multiprocess_mode="livesum",
)

#: Connections the pool opened beyond `pool_size`, up to `max_overflow`.
#: Sustained overflow means the steady-state pool is undersized, which is a
#: different problem from a leak and is fixed differently.
POSTGRES_POOL_OVERFLOW: Final[Gauge] = Gauge(
    "postgres_pool_connections_overflow",
    "Connections opened beyond the configured pool size.",
    multiprocess_mode="livesum",
)

#: 1 when a dependency answered its health probe, 0 when it did not.
#: `dependency` is `postgres` or `redis`. This is the same fact `/healthz`
#: returns to Better Stack, exported so the two agree — an external checker
#: that says "down" while the internal gauge says "up" is a network problem,
#: and being able to tell those apart is most of the first minute of an
#: incident.
#:
#: `livemin`: down anywhere is down.
DEPENDENCY_UP: Final[Gauge] = Gauge(
    "dependency_up",
    "1 when a backing dependency answered its probe, 0 when it did not.",
    ["dependency"],
    multiprocess_mode="livemin",
)

#: Probe latency, so a dependency that is technically up but slow is visible
#: before it becomes a dependency that is down.
DEPENDENCY_PROBE_DURATION: Final[Histogram] = Histogram(
    "dependency_probe_duration_seconds",
    "Time taken by one dependency health probe.",
    ["dependency"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 3.0),
)

#: Build identity, carried as labels on a constant 1. The conventional way to
#: get a version into Prometheus, and worth having because the first question
#: about any change in a graph is "did we deploy".
APP_INFO: Final[Gauge] = Gauge(
    "app_info",
    "Deployment identity; always 1, the labels carry the information.",
    ["version", "environment", "component"],
    multiprocess_mode="livemostrecent",
)


def set_app_info(*, version: str, environment: str, component: str) -> None:
    """Publish this process's build identity.

    Args:
        version: The release, from the package metadata.
        environment: ``local`` / ``staging`` / ``production``.
        component: ``api``, ``worker`` or ``beat`` — so a graph can tell which
            half of the deployment a series came from.
    """
    APP_INFO.labels(version=version, environment=environment, component=component).set(1)


__all__ = [
    "APP_INFO",
    "CELERY_QUEUE_LENGTH",
    "CELERY_TASKS",
    "CELERY_TASK_DURATION",
    "DEPENDENCY_PROBE_DURATION",
    "DEPENDENCY_UP",
    "HARVEST_DURATION",
    "HARVEST_PARTIAL",
    "HARVEST_ROWS",
    "POSTGRES_POOL_FREE",
    "POSTGRES_POOL_OVERFLOW",
    "POSTGRES_POOL_USED",
    "SECURITY_AUTH_FAILURES",
    "SECURITY_DEGRADED_CONTROLS",
    "SECURITY_RLS_VIOLATIONS",
    "WB_API_DURATION",
    "WB_API_REQUESTS",
    "WB_RATE_LIMIT_REMAINING",
    "WB_RATE_LIMIT_WAIT",
    "set_app_info",
]
