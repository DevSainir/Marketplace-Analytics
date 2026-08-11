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

The lock is **held by a heartbeat, not by a long TTL**, and that is the whole
point of the renewal below. A TTL long enough to cover the slowest run is also
long enough to strand the job when the process dies without releasing it, and
processes die routinely: on 2026-08-11 the finance harvest was orphaned twice
in one morning — once by the OOM killer, once by a deploy recreating the worker
mid-walk — each time leaving an hour-long lock behind that the next scheduled
tick found held and skipped. A short TTL that a live holder keeps renewing
inverts that: a healthy run holds the lock indefinitely, and a dead one lets go
within one TTL.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager, suppress
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

#: Extend our own lock, never anybody else's. Same token check as the release:
#: a holder that already lost the lock to a timeout must not silently take it
#: back out from under the run that replaced it.
_RENEW_IF_OWNED = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""

#: Renewals per TTL. Three means two consecutive renewals can be lost — to a
#: blocked event loop or a Redis blip — before the lock lapses under a run that
#: is still alive.
_RENEWALS_PER_TTL = 3


def _millis(seconds: float) -> int:
    """Redis expiry in milliseconds, never rounded down to 'no expiry at all'."""
    return max(int(seconds * 1000), 1)


@asynccontextmanager
async def single_flight(key: str, *, ttl_seconds: float, redis: Redis) -> AsyncIterator[bool]:
    """Hold a cross-process lock on ``key`` for the duration of the block.

    Args:
        key: Redis key naming the job, e.g. ``"finreports:harvest_finance"``.
        ttl_seconds: How long the lock outlives a holder that stops renewing it.
            This is NOT the job's expected runtime — a live holder renews and so
            keeps the lock as long as it runs. Size it against the longest the
            holder might fail to renew for while still healthy (a blocked event
            loop, a Redis blip), because that is what would let a second run in;
            and against how long a dead holder may strand the job, because that
            is what it costs when the process is killed.
        redis: The shared async Redis client.

    Yields:
        ``True`` when the caller holds the lock and should do the work,
        ``False`` when another run already holds it. Yields ``True`` when Redis
        itself is unreachable — see the module docstring on failing open.
    """
    token = uuid.uuid4().hex
    try:
        # Milliseconds throughout, so the TTL is a real number of seconds and
        # not an integer floor — the renewal interval below is a fraction of it.
        acquired = bool(await redis.set(key, token, nx=True, px=_millis(ttl_seconds)))
    except RedisError as exc:
        logger.warning(
            "single_flight: Redis unavailable for %s (%s) — running unguarded.", key, exc
        )
        yield True
        return

    heartbeat = (
        asyncio.create_task(_renew_until_cancelled(key, token=token, ttl=ttl_seconds, redis=redis))
        if acquired
        else None
    )
    try:
        yield acquired
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            # Awaited, not just cancelled: an un-awaited cancelled task logs
            # "Task exception was never retrieved" at GC time, in a worker whose
            # logs are the only view into what the harvest did.
            with suppress(asyncio.CancelledError):
                await heartbeat
        if acquired:
            try:
                # ``eval`` is typed sync-or-async across both clients; on the
                # async one it is always awaitable (as in the WB rate gate).
                await cast(Awaitable[Any], redis.eval(_RELEASE_IF_OWNED, 1, key, token))
            except RedisError as exc:
                logger.warning(
                    "single_flight: could not release %s (%s) — it expires in %.0fs.",
                    key,
                    exc,
                    ttl_seconds,
                )


async def _renew_until_cancelled(key: str, *, token: str, ttl: float, redis: Redis) -> None:
    """Keep extending our lock until the holder's block exits.

    Runs alongside the guarded work on the same event loop, which is what makes
    "still renewing" mean "still alive": a process that is killed, or one whose
    loop has stopped turning, stops renewing and the lock lapses on its own.

    A failed renewal is logged and retried rather than raised — the work it
    guards must not die because Redis hiccuped, and losing one of three
    renewals per TTL is survivable by construction.
    """
    # Floored only to keep a nonsensically small TTL from spinning; every real
    # caller's interval comes from the division.
    interval = max(ttl / _RENEWALS_PER_TTL, 0.05)
    while True:
        await asyncio.sleep(interval)
        try:
            await cast(
                Awaitable[Any], redis.eval(_RENEW_IF_OWNED, 1, key, token, str(_millis(ttl)))
            )
        except RedisError as exc:
            logger.warning("single_flight: could not renew %s (%s) — retrying.", key, exc)


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
