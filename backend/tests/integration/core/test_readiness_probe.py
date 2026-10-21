"""The readiness probe against the real Postgres and Redis.

The component tier proves the parts that live in this process — the status
mapping, the payload's shape, that no exception text escapes — with both probes
faked. It has to fake them: that tier forbids reaching a real database, and
``/healthz`` deliberately opens its own session rather than taking one from
``get_db``, so it walks straight past the dependency override that guards it.

What is left is the half only a real dependency can answer, and it is the half
the whole endpoint is for: **does the query this probe runs actually work
against the thing it claims to be checking**. A readiness probe that returns
``ok`` because its ``SELECT 1`` was faked would pass every test in the suite and
tell an external uptime checker nothing at all.

The Redis case is the same question from the other side, and it is the one worth
having: this suite can point the client at a dead endpoint, which is the only
way to see the probe report ``down`` for a reason it did not invent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from redis.asyncio import Redis

from src.core import redis as redis_module
from src.core.observability.health import POSTGRES, REDIS, check_health

pytestmark = pytest.mark.usefixtures("postgres_ready")


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> Any:
    """Drain the process-wide pool around each test in this module.

    A harness artefact, not a production one, and worth naming so nobody
    "fixes" the probe over it. ``_ping_postgres`` deliberately takes a
    connection from the shared engine — acquiring one is part of what the probe
    tests, since the incident behind these metrics was a pool where every
    connection was alive and none could be obtained. asyncpg binds a pooled
    connection to the loop that opened it, and pytest-asyncio gives each test a
    NEW loop, so the second test in this file would otherwise inherit the
    first's socket and die with "attached to a different loop" before probing
    anything.

    Production has one loop for the life of the process. The place this
    genuinely bites is the Celery worker, which runs a loop per task — and that
    is already handled, by :func:`src.core.tasks.run_task` draining both pools
    at every task boundary.
    """
    from src.core.database import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


async def test_the_probe_really_reaches_postgres_and_redis(redis_client: Any) -> None:
    """Both dependencies answer, and the probe says so.

    The baseline that stops every other case here passing vacuously — and the
    one assertion the component tier structurally cannot make.
    """
    # Act
    report = await check_health()

    # Assert
    assert report.healthy
    by_name = {dependency.name: dependency for dependency in report.dependencies}
    assert by_name[POSTGRES].healthy
    assert by_name[REDIS].healthy
    # A real round trip takes measurable time; a zero here would mean the probe
    # short-circuited rather than asked.
    assert by_name[POSTGRES].latency_ms > 0


async def test_a_dead_redis_is_reported_down_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable dependency must produce a 503, never a 500.

    Pointed at a closed port, which is the honest way to test this: the probe's
    contract is that it converts "I could not reach this" into a reported fact,
    and a mock raising a chosen exception type would only prove we catch the
    type we thought of.
    """
    # Arrange — the single accessor is the single seam (see src.core.redis).
    dead = Redis.from_url("redis://127.0.0.1:1/0", decode_responses=True)
    monkeypatch.setattr(redis_module, "_redis", dead)

    # Act
    report = await check_health()

    # Assert
    by_name = {dependency.name: dependency for dependency in report.dependencies}
    assert not by_name[REDIS].healthy
    assert not report.healthy, "one dead dependency makes the whole probe unhealthy"
    # Postgres is untouched, and the report still distinguishes them — which is
    # most of the first minute of an incident.
    assert by_name[POSTGRES].healthy
    await dead.aclose()


async def test_a_hanging_dependency_does_not_hang_the_probe(
    monkeypatch: pytest.MonkeyPatch, redis_client: Any
) -> None:
    """The timeout is the property, and it is the one that matters under load.

    A wedged dependency is worse than a dead one: it is up, so nothing refuses,
    and every probe request sits on it until the caller gives up. Without a
    bound, the endpoint that exists to measure the service's health becomes a
    way to consume its capacity — at exactly the moment it has none spare.
    """

    # Arrange
    async def _never_answers() -> None:
        await asyncio.sleep(30)

    monkeypatch.setattr("src.core.observability.health._ping_redis", _never_answers)

    # Act
    report = await asyncio.wait_for(check_health(), timeout=10)

    # Assert
    by_name = {dependency.name: dependency for dependency in report.dependencies}
    assert not by_name[REDIS].healthy
    # It gave up at its own budget rather than at the caller's.
    assert by_name[REDIS].latency_ms < 5_000
    # And the two ran concurrently, so a second dead dependency would not have
    # doubled the wait — the worst case is the largest timeout, not their sum.
    assert by_name[POSTGRES].healthy
