"""Gauges that are read, not incremented — sampled once per scrape.

A counter is written where the thing happens. A gauge like "how many
connections are checked out" or "how long is the queue" has no such moment: it
is a fact about a live system that is true continuously and interesting only
when somebody asks. So these are sampled at scrape time, from the exposition
route, rather than maintained by the code they describe.

**Derived, never accumulated.** The queue length is read from Redis with
``LLEN``, not tracked by incrementing on enqueue and decrementing on
completion. The pool figures are read off the pool object, not tracked by
counting checkouts. Both could be maintained the other way, and both would
then be a *model* of the system that drifts from it the first time a message is
lost or a connection is closed out of band — and a monitoring system that
disagrees with reality is worse than one that is absent, because it is
believed.

**Nothing here may raise.** A failed sample must cost one stale gauge, never
the scrape: Prometheus receiving no data at all is how a dependency outage
turns into a monitoring outage at exactly the moment monitoring is needed.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Iterator
from pathlib import Path
from typing import Final, cast

from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import text
from sqlalchemy.pool import QueuePool

from src.core.config import settings
from src.core.database import engine
from src.core.degradation import (
    CONTROL_AUTH_RATE_LIMIT,
    CONTROL_LOGIN_BACKOFF,
    CONTROL_SESSION_REVOCATION,
    degraded_controls,
)
from src.core.logging import get_logger
from src.core.observability.metrics import (
    CELERY_QUEUE_LENGTH,
    POSTGRES_POOL_FREE,
    POSTGRES_POOL_OVERFLOW,
    POSTGRES_POOL_USED,
    POSTGRES_STATS_RESET,
    SECURITY_DEGRADED_CONTROLS,
)
from src.core.redis import get_redis

logger = get_logger(__name__)

#: Queues whose depth is sampled. Celery routes everything to its default
#: queue here — there are no ``task_routes`` and no ``queue=`` on any
#: ``apply_async`` — so this is a one-entry tuple that names the assumption
#: rather than leaving it implicit. Adding a route means adding it here, and a
#: queue nobody samples is a queue that can back up unobserved.
_QUEUES: Final[tuple[str, ...]] = ("celery",)

#: Every control the degradation ledger can report on (P1.2). Listed so the
#: gauge can be set back to 0 when a control recovers: a gauge that is only
#: ever written on degradation stays at 1 forever, and an alert that never
#: clears is one people learn to ignore.
#:
#: Imported from the ledger rather than spelled out here — a copied string
#: would silently stop matching the day a control is renamed, and the symptom
#: would be a gauge that reads healthy because nothing ever writes to it.
_CONTROLS: Final[tuple[str, ...]] = (
    CONTROL_AUTH_RATE_LIMIT,
    CONTROL_SESSION_REVOCATION,
    CONTROL_LOGIN_BACKOFF,
)


#: Where cgroup v2 publishes what a container is charged for and what it is
#: allowed. Read rather than derived: this is the kernel's own accounting, and
#: it is the exact pair of numbers it compares before sending a SIGKILL.
_CGROUP_USAGE = Path("/sys/fs/cgroup/memory.current")
_CGROUP_LIMIT = Path("/sys/fs/cgroup/memory.max")

#: The two series :class:`CgroupMemoryCollector` publishes, named here because
#: `alerts.yml` divides one by the other and nothing else in this codebase
#: declares them — they are produced by a collector rather than by a metric
#: object, so the scan in `tests/unit/core/test_alert_rules.py` cannot see them.
#: A test binds the alert to these constants instead.
CGROUP_MEMORY_USED_SERIES: Final[str] = "celery_worker_memory_bytes"
CGROUP_MEMORY_LIMIT_SERIES: Final[str] = "celery_worker_memory_limit_bytes"


def _read_cgroup_bytes(path: Path) -> float | None:
    """Read one cgroup memory file, or ``None`` when it says nothing usable.

    ``memory.max`` holds the literal ``max`` on an unlimited cgroup, and neither
    file exists outside cgroup v2 (a developer's macOS, a v1 host). Both are
    "there is no number here", and absent is the honest exposition for that —
    a zero would be read as a limit of nothing.
    """
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class CgroupMemoryCollector:
    """Publishes the worker container's memory against its ceiling, per scrape.

    **The one number the OOM kills were invisible in.** Three prefork children
    were SIGKILLed in the twelve hours to 2026-09-17 01:06 and Prometheus held
    no evidence of any of them: `process_resident_memory_bytes` comes from
    `prometheus_client`'s default process collector, which multiprocess mode
    drops — so of this deployment only the two API containers ever reported a
    resident set, and the one container whose working set is driven by data
    volume reported none. The kills were found in `dmesg`, by hand, the morning
    after.

    A collector rather than a gauge somebody sets, for the reason the module
    docstring gives: this is a fact about a live system, true continuously, and
    a gauge written at task boundaries would miss the growth *inside* the task —
    which is the only place it has ever mattered.

    Unlabelled, and deliberately: `/metrics` has no tenancy check because it has
    no tenant, and "which container" is already the scrape target's job.
    """

    def collect(self) -> Iterator[GaugeMetricFamily]:
        """Yield current usage and the ceiling, omitting whichever is unknown."""
        usage = _read_cgroup_bytes(_CGROUP_USAGE)
        if usage is not None:
            gauge = GaugeMetricFamily(
                CGROUP_MEMORY_USED_SERIES,
                "Memory this worker's cgroup is charged for, parent and children together.",
            )
            gauge.add_metric([], usage)
            yield gauge
        limit = _read_cgroup_bytes(_CGROUP_LIMIT)
        if limit is not None:
            ceiling = GaugeMetricFamily(
                CGROUP_MEMORY_LIMIT_SERIES,
                "The cgroup ceiling the kernel compares that usage against.",
            )
            ceiling.add_metric([], limit)
            yield ceiling


#: The pair :class:`MetricsDirCollector` publishes, named for the same reason
#: as the cgroup pair above: `alerts.yml` divides one by the other.
METRICS_DIR_USED_SERIES: Final[str] = "celery_worker_metrics_dir_bytes"
METRICS_DIR_SIZE_SERIES: Final[str] = "celery_worker_metrics_dir_size_bytes"


class MetricsDirCollector:
    """Publishes how full the worker's multiprocess-metrics tmpfs is, per scrape.

    **A full mount kills the worker outright.** Every process that writes a
    metric extends an mmap'd file there; on a tmpfs with no pages left the
    kernel answers that write with SIGBUS, not with an error Python can catch.
    On 2026-10-15 it filled at 04:01 MSK and every task died on start for three
    hours — reported only as `WorkerKilled`, whose text pointed at memory.

    Read from ``statvfs`` rather than by summing the files: a file's length is
    the mmap's reservation, the filesystem's count is what is actually charged,
    and only the second one is what runs out.
    """

    def collect(self) -> Iterator[GaugeMetricFamily]:
        """Yield the bytes used and the mount's size, or nothing outside the worker."""
        directory = settings.prometheus_multiproc_dir.strip()
        if not directory:
            return
        try:
            stats = os.statvfs(directory)
        except OSError:
            return
        used = GaugeMetricFamily(
            METRICS_DIR_USED_SERIES,
            "Bytes used on the filesystem holding the worker's multiprocess metric files.",
        )
        used.add_metric([], (stats.f_blocks - stats.f_bfree) * stats.f_frsize)
        yield used
        size = GaugeMetricFamily(
            METRICS_DIR_SIZE_SERIES,
            "Size of that filesystem; a write past it kills the writing process with SIGBUS.",
        )
        size.add_metric([], stats.f_blocks * stats.f_frsize)
        yield size


def sample_pool() -> None:
    """Read the SQLAlchemy pool's occupancy into its gauges.

    ``QueuePool`` is the only pool type that reports these; a ``NullPool``
    (which the tests and Alembic use) reports nothing, so the sample is skipped
    rather than guessed at. Skipping leaves the gauges at their previous value,
    which for a process that never had a real pool is "never set" — absent from
    the exposition, which is the honest answer.
    """
    pool = engine.pool
    if not isinstance(pool, QueuePool):
        return
    try:
        POSTGRES_POOL_USED.set(pool.checkedout())
        POSTGRES_POOL_FREE.set(pool.checkedin())
        POSTGRES_POOL_OVERFLOW.set(max(pool.overflow(), 0))
    except Exception:
        logger.warning("Could not sample the connection pool.", exc_info=True)


async def sample_queue_depth() -> None:
    """Read each Celery queue's depth from the broker.

    The broker is Redis and a Celery queue is a Redis list, so ``LLEN`` is the
    queue's length by definition rather than by inference. ``unacked`` is the
    hash of messages a worker has taken but not yet acknowledged — with
    ``task_acks_late`` on (see :mod:`src.core.celery_app`) that is "work in
    progress", and it is the number that stays high when a task is wedged,
    while the queue itself looks empty.
    """
    redis = get_redis()
    for queue in _QUEUES:
        try:
            depth = await cast(Awaitable[int], redis.llen(queue))
        except Exception:
            # Every exception, matching this module's stated contract. Not only
            # RedisError: a drained connection pool answers "Event loop is
            # closed", a RuntimeError that has silently voided Redis reads in
            # this codebase before (`src.core.redis.drain_redis_pool`), and the
            # list of things that are "obviously" the only failures is exactly
            # the list that was wrong last time.
            #
            # `exc_info` rather than just the type name: swallowing broadly is
            # only safe if the swallowed thing is still visible somewhere, or a
            # typo here becomes a gauge that is stale forever and looks fine.
            logger.warning("Could not sample queue %s.", queue, exc_info=True)
            continue
        CELERY_QUEUE_LENGTH.labels(queue_name=queue).set(depth)
    try:
        in_progress = await cast(Awaitable[int], redis.hlen("unacked"))
    except Exception:
        logger.warning("Could not sample the unacked set.", exc_info=True)
        return
    CELERY_QUEUE_LENGTH.labels(queue_name="unacked").set(in_progress)


def sample_degraded_controls() -> None:
    """Mirror the degradation ledger (P1.2) into a gauge an alert can bind to.

    Every known control is written on every scrape, not just the degraded
    ones. That is the difference between an alert that clears and one that
    latches: writing only on degradation leaves the gauge at 1 after recovery,
    and a stuck alert is indistinguishable from a real one until somebody
    checks by hand.
    """
    degraded = set(degraded_controls())
    for control in _CONTROLS:
        SECURITY_DEGRADED_CONTROLS.labels(control=control).set(1 if control in degraded else 0)


#: As long as the readiness probe allows itself, for the same reason: a
#: database that does not answer must cost the scrape seconds, not the scrape.
_STATS_RESET_TIMEOUT_SECONDS: Final[float] = 2.0


async def sample_postgres_stats_reset() -> None:
    """Publish when PostgreSQL last discarded its statistics — i.e. last crashed.

    See :data:`~src.core.observability.metrics.POSTGRES_STATS_RESET` for why
    this row, of all of them. ``pg_stat_bgwriter`` rather than
    ``pg_stat_database``: its ``stats_reset`` is always set, while a database's
    is NULL until something resets it.
    """
    try:
        async with asyncio.timeout(_STATS_RESET_TIMEOUT_SECONDS), engine.connect() as connection:
            reset_at = await connection.scalar(
                text("SELECT extract(epoch FROM stats_reset) FROM pg_stat_bgwriter")
            )
    except Exception as exc:
        # Same breadth, and the same reason, as the readiness probe: whatever
        # went wrong, a failed sample costs one stale gauge and never the scrape.
        logger.warning("Could not read pg_stat_bgwriter: %s: %s", type(exc).__name__, exc)
        return
    if reset_at is not None:
        POSTGRES_STATS_RESET.set(float(reset_at))


async def refresh_sampled_metrics() -> None:
    """Refresh every scrape-time gauge, in the order they are cheapest.

    Called from the exposition route immediately before rendering, so a scrape
    reflects the moment it was taken rather than the last time something
    happened to change.
    """
    sample_pool()
    sample_degraded_controls()
    await sample_queue_depth()
    await probe_dependencies()
    await sample_postgres_stats_reset()


async def probe_dependencies() -> None:
    """Ping Postgres and Redis so ``dependency_up`` exists between health checks.

    :func:`~src.core.observability.health.check_health` writes ``dependency_up``
    and ``dependency_probe_duration_seconds`` as a side effect, so this drives
    the same probe the readiness endpoint does and throws the report away.

    **Why the scrape has to do this itself.** Those gauges were written only
    when something called ``/healthz`` — which meant the ``DependencyDown``
    alert (``dependency_up == 0``) silently depended on an external uptime
    checker existing and polling. With nobody polling, the series is simply
    absent after a container restart, and an alert with no series never fires:
    the rule reads as covering Postgres and Redis while covering nothing at
    all. That is a worse state than having no rule, because the dashboard is
    green either way. Found on the deployed box, where a deploy had recreated
    the API and nothing had asked it for its readiness since.

    Driving it from the scrape makes the alert self-sufficient: Prometheus asks
    every 15 s whether these are reachable, whether or not UptimeRobot is
    configured, and the two now answer the same question independently rather
    than one depending on the other.

    The cost is one ``SELECT 1`` and one ``PING`` per scrape per API instance —
    a handful a minute, on the same pools a request would use. Both probes are
    already bounded by their own timeout and cannot raise, so a dead dependency
    slows the scrape rather than failing it.
    """
    # Imported here rather than at module scope: `health` imports this module's
    # own metrics, and the exposition route imports both. Keeping the edge
    # local to the one function that needs it avoids widening the import graph
    # of a package whose `__init__` is deliberately thin.
    from src.core.observability.health import check_health

    await check_health()


__all__ = [
    "CGROUP_MEMORY_LIMIT_SERIES",
    "CGROUP_MEMORY_USED_SERIES",
    "CgroupMemoryCollector",
    "probe_dependencies",
    "refresh_sampled_metrics",
    "sample_degraded_controls",
    "sample_pool",
    "sample_postgres_stats_reset",
    "sample_queue_depth",
]
