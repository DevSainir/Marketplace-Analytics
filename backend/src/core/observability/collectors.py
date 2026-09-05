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

from collections.abc import Awaitable
from typing import Final, cast

from sqlalchemy.pool import QueuePool

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
    every 15 s whether these are reachable, whether or not Better Stack is
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
    "probe_dependencies",
    "refresh_sampled_metrics",
    "sample_degraded_controls",
    "sample_pool",
    "sample_queue_depth",
]
