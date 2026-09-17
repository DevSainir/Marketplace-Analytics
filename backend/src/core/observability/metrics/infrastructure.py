"""Pool, dependency and build-identity metrics.

The two pools and the two dependencies, plus the constant-1 gauge that answers
the first question asked about any change in a graph: did we deploy.
"""

from __future__ import annotations

from typing import Final

from prometheus_client import Gauge, Histogram

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
