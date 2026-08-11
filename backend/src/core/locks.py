"""Redis-backed single-flight lock for scheduled jobs.

A Celery beat entry that fires more often than its task can finish will happily
start a second copy alongside the first. For a job that only reads that is
wasteful; for one that walks a rate-limited third-party API it is corrupting,
because the two copies spend each other's request budget and the loser's windows
come back as errors the caller records as "nothing there".

The lock is therefore keyed per job, not per worker: it must hold across
processes and across hosts, so it lives in Redis rather than in the worker.

Availability policy matches :mod:`src.core.redis` — **fail open**. If Redis
cannot answer, the caller runs. A harvest that overlaps is a bad day; a harvest
that stops happening because the cache is down is the failure this repo has
already paid for once, and it is silent.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.logging import get_logger

logger = get_logger(__name__)

#: Release only the lock we ourselves took. Without the token comparison, a run
#: that overran its TTL would delete the *next* run's lock on its way out and
#: leave the job unguarded exactly when it is already running long.
_RELEASE_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


@asynccontextmanager
async def single_flight(key: str, *, ttl_seconds: int, redis: Redis) -> AsyncIterator[bool]:
    """Hold a cross-process lock on ``key`` for the duration of the block.

    Args:
        key: Redis key naming the job, e.g. ``"finreports:harvest_finance"``.
        ttl_seconds: How long the lock survives without being released. Set it
            above the job's worst plausible runtime: too low and a long run gets
            joined by the next tick anyway, too high and a worker killed
            mid-run blocks the job until it expires.
        redis: The shared async Redis client.

    Yields:
        ``True`` when the caller holds the lock and should do the work,
        ``False`` when another run already holds it. Yields ``True`` when Redis
        itself is unreachable — see the module docstring on failing open.
    """
    token = uuid.uuid4().hex
    try:
        acquired = bool(await redis.set(key, token, nx=True, ex=ttl_seconds))
    except RedisError as exc:
        logger.warning(
            "single_flight: Redis unavailable for %s (%s) — running unguarded.", key, exc
        )
        yield True
        return

    try:
        yield acquired
    finally:
        if acquired:
            try:
                # ``eval`` is typed sync-or-async across both clients; on the
                # async one it is always awaitable (as in the WB rate gate).
                await cast(Awaitable[Any], redis.eval(_RELEASE_IF_OWNED, 1, key, token))
            except RedisError as exc:
                logger.warning(
                    "single_flight: could not release %s (%s) — it expires in %ds.",
                    key,
                    exc,
                    ttl_seconds,
                )


async def is_held(key: str, *, redis: Redis) -> bool:
    """Whether someone currently holds the lock on ``key``.

    Advisory only, and deliberately so: between this answer and any decision
    made on it the lock can be taken or dropped. It exists to tell a *user* that
    a job is already running, not to serialise anything — :func:`single_flight`
    is what actually keeps two runs apart.

    Args:
        key: The same key the job passes to :func:`single_flight`.
        redis: The shared async Redis client.

    Returns:
        ``True`` when the key exists. ``False`` when Redis cannot answer —
        matching the fail-open policy above: an unreachable cache must not make
        the app claim a harvest is running and refuse to start one.
    """
    try:
        return bool(await redis.exists(key))
    except RedisError as exc:
        logger.warning("single_flight: could not read %s (%s) — reporting free.", key, exc)
        return False


__all__ = ["is_held", "single_flight"]
