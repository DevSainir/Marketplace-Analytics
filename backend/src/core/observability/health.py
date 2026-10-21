"""What ``/healthz`` actually checks, and what it is allowed to say back.

``/health`` already existed and answers a static payload — that is a *liveness*
probe, and it is the right shape for one: Docker restarts a container that
stops answering, and a liveness probe that fails because Postgres is down would
have Docker restart a perfectly good API process in the middle of a database
outage, turning one problem into two.

This is the other kind. ``/healthz`` is a *readiness* probe: it asks whether
this process can do its job right now, which means asking its two backing
stores. UptimeRobot polls it from outside the network, so it is also the thing
that notices the box is unreachable — the failure mode no internal check can
observe, because a check that cannot run reports nothing rather than reporting
down.

Three rules this file exists to keep
------------------------------------
**A probe must never hang.** Every check runs under a timeout well below the
external checker's own, so a wedged dependency produces a fast "down" instead
of a request that occupies a worker until UptimeRobot gives up. A health
endpoint that stalls is one that consumes the capacity it was meant to
measure — and it stalls exactly when the system is already struggling.

**A probe must never leak.** The response says which dependency is unhealthy
and how long the check took. It never carries the exception text, which is a
DSN, a hostname, or a PostgreSQL error naming a role and a database (register
P0.3 removed exactly this class of disclosure from the API's error path, and a
public health endpoint is not the place to put it back). The text goes to the
logs, where it is useful and access-controlled.

**A probe must be cheap.** ``SELECT 1`` and ``PING``, on the shared pools. No
table is read, so an unbounded poll cannot become load, and neither check
touches tenant data — which is why this route needs no tenancy guard rather
than having one that would be nonsense here.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Final

from sqlalchemy import text

from src.core.database import AsyncSessionLocal
from src.core.logging import get_logger
from src.core.observability.metrics import DEPENDENCY_PROBE_DURATION, DEPENDENCY_UP
from src.core.redis import get_redis

logger = get_logger(__name__)

#: Per-dependency budget. Two seconds is chosen against the *checker's*
#: timeout, not against normal latency: an uptime checker waits tens of
#: seconds, both probes run concurrently, and this leaves the endpoint
#: answering in single digits even when everything it asks is dead. Normal is under 5 ms, so a
#: probe anywhere near this ceiling is already a finding.
_PROBE_TIMEOUT_SECONDS: Final[float] = 2.0

#: Dependency names, used as the metric label and the response key. Fixed
#: strings rather than derived ones, because a dashboard and an alert rule are
#: written against them.
POSTGRES: Final[str] = "postgres"
REDIS: Final[str] = "redis"


@dataclass(frozen=True, slots=True)
class DependencyHealth:
    """One dependency's answer.

    Attributes:
        name: ``postgres`` or ``redis``.
        healthy: Whether it answered within the budget.
        latency_ms: How long the probe took, rounded — reported even on
            failure, where it distinguishes "refused instantly" (the process is
            down) from "took the full timeout" (it is up and wedged, which is
            the worse of the two and the one that looks fine from outside).
    """

    name: str
    healthy: bool
    latency_ms: float


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The whole answer, and whether it is a 200.

    Attributes:
        dependencies: One entry per checked backing store.
    """

    dependencies: tuple[DependencyHealth, ...]

    @property
    def healthy(self) -> bool:
        """Whether every dependency answered.

        All-or-nothing on purpose. This service cannot serve a request without
        Postgres, and without Redis it serves them with its rate limiter and
        session revocation failing open — which is degraded in
        a way that should page somebody, not a state to report as healthy.
        """
        return all(dependency.healthy for dependency in self.dependencies)

    def as_payload(self) -> dict[str, object]:
        """Render the response body.

        Returns:
            A small object: overall status plus a per-dependency breakdown.
            No exception text, no host names, no versions — see the module
            docstring for why a public probe says this little.
        """
        return {
            "status": "ok" if self.healthy else "degraded",
            "dependencies": {
                dependency.name: {
                    "status": "ok" if dependency.healthy else "down",
                    "latency_ms": dependency.latency_ms,
                }
                for dependency in self.dependencies
            },
        }


async def _timed(name: str, probe: object) -> DependencyHealth:
    """Run one probe under the timeout and record its metrics.

    Args:
        name: Dependency label.
        probe: The awaitable doing the actual check.

    Returns:
        The dependency's health. Never raises — a probe that raised would take
        down the endpoint whose job is to report that something is down.
    """
    started = time.perf_counter()
    healthy = False
    try:
        await asyncio.wait_for(probe, timeout=_PROBE_TIMEOUT_SECONDS)  # type: ignore[arg-type]
        healthy = True
    except TimeoutError:
        logger.warning("Health probe for %s timed out after %.1fs.", name, _PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        # Deliberately every exception, not the four driver types one would
        # list. A narrower catch reads as more careful and is not: an exception
        # it does not name escapes, and the endpoint whose entire job is to
        # report that something is broken answers 500 instead of reporting it.
        # Every reason a probe can fail — a driver error, a DNS failure, a
        # misconfigured client, a bug in this file — is the same fact to
        # whoever is polling: this dependency is not usable.
        #
        # The text goes here and only here (see the module docstring), and the
        # scrubber strips a DSN password out of it on the way (P2.2).
        logger.warning("Health probe for %s failed: %s: %s", name, type(exc).__name__, exc)
    elapsed_seconds = time.perf_counter() - started
    DEPENDENCY_PROBE_DURATION.labels(dependency=name).observe(elapsed_seconds)
    DEPENDENCY_UP.labels(dependency=name).set(1 if healthy else 0)
    return DependencyHealth(name=name, healthy=healthy, latency_ms=round(elapsed_seconds * 1000, 2))


async def _ping_postgres() -> None:
    """Take a pooled connection and ask it the cheapest possible question.

    A fresh session rather than the request's: this route has no session
    dependency, and taking one from the pool is itself part of what is being
    tested — the incident this metric family exists for was pool exhaustion,
    where every connection was alive and none could be obtained.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))


async def _ping_redis() -> None:
    """Ask Redis to answer PONG on the shared client's pool."""
    await get_redis().ping()


async def check_health() -> HealthReport:
    """Probe every backing store concurrently and report.

    Concurrently rather than in sequence: the two are independent, and a
    sequential probe would make the endpoint's worst case the *sum* of the
    timeouts rather than the largest of them — which is the difference between
    answering in two seconds and four when everything is down at once.

    Returns:
        The report. Callers map :attr:`HealthReport.healthy` onto 200 or 503.
    """
    postgres, redis = await asyncio.gather(
        _timed(POSTGRES, _ping_postgres()),
        _timed(REDIS, _ping_redis()),
    )
    return HealthReport(dependencies=(postgres, redis))


__all__ = [
    "POSTGRES",
    "REDIS",
    "DependencyHealth",
    "HealthReport",
    "check_health",
]
