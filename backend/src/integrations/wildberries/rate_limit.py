"""Client-side pacing for WB's per-endpoint token buckets.

WB does not merely answer 429 when a bucket is empty. Measured live on
2026-07-30 against the analytics surface, an over-budget request comes back as
HTTP 500 (``x-ratelimit-remaining: 0``) or — worse — the connection is simply
held open until the client's own read timeout fires. Retrying is what turned a
two-second refresh into a three-minute one: the backoff ladder starts at 2s,
well inside a 20s bucket window, so every attempt landed in the same empty
bucket and paid another 30s timeout.

The cure is to not send the request until a token exists. WB publishes the
truth in ``x-ratelimit-remaining``, so the gate below mirrors WB's bucket and
folds that header back in on every response.

The bucket must be shared across PROCESSES, not just coroutines: Celery runs a
prefork pool, so the nightly cohort pass and an interactive «Обновить» for the
same workspace are different OS processes holding one WB token between them.
That is why the state lives in Redis and not in an :class:`asyncio.Semaphore`.

Availability policy follows :mod:`src.core.redis` — **fail open**. A Redis
outage degrades to per-process pacing (an in-memory bucket) rather than
stopping every harvest; the degradation is logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)

#: Take a token, or report how many milliseconds until one exists. The Redis
#: server clock (``TIME``) is the reference so every process agrees without
#: trusting container clocks.
_ACQUIRE_SLOT_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local capacity = tonumber(ARGV[1])
local refill_ms = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now_ms
end
local elapsed = now_ms - ts
if elapsed > 0 then
  tokens = math.min(capacity, tokens + elapsed / refill_ms)
  ts = now_ms
end
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = math.ceil((1 - tokens) * refill_ms)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', ts)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return wait
"""

#: Clamp our bucket to what WB just said it has left. Never raises our estimate
#: above WB's: a header of 0 empties the bucket, so the next caller waits a
#: full refill instead of walking into a 500.
_CLAMP_SLOTS_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local remaining = tonumber(ARGV[1])
local ttl_ms = tonumber(ARGV[2])
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(state[1])
if tokens == nil or remaining < tokens then
  tokens = remaining
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return tostring(tokens)
"""


class RateGate(Protocol):
    """A pre-flight gate a WB client passes before every HTTP attempt."""

    async def acquire(self, endpoint: str) -> None:
        """Block until this endpoint's bucket holds a token."""
        ...

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Fold WB's ``x-ratelimit-remaining`` back into the bucket."""
        ...


class NullRateGate:
    """A gate that never waits — for surfaces with no measured bucket, and tests."""

    async def acquire(self, endpoint: str) -> None:
        """Return immediately; this surface is not paced."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Ignore WB's rate headers; nothing is being paced."""
        return


class TokenBucketRateGate:
    """A distributed token bucket mirroring one WB endpoint bucket per token.

    Keyed by ``(surface, endpoint, token fingerprint)``: WB meters per endpoint
    (verified live — a funnel call answering ``remaining: 2`` sat next to a
    stocks call answering ``remaining: 0``), and per seller token, so one
    workspace's harvest must not throttle another's.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        surface: str,
        token: str,
        capacity: int,
        refill_seconds: float,
        max_wait_seconds: float,
    ) -> None:
        """Configure the bucket.

        Args:
            redis: Shared async client (the process-wide pool).
            surface: WB API family, e.g. ``"analytics"`` — part of the key.
            token: The seller token whose bucket this is. Only a truncated
                SHA-256 of it is stored, so Redis never holds a credential.
            capacity: Burst size WB allows before the bucket empties.
            refill_seconds: Seconds WB takes to grant one token back.
            max_wait_seconds: Give up (raise) rather than queue longer than
                this — a caller waiting forever is worse than a failed harvest
                the retry policy can reschedule.
        """
        self._redis = redis
        self._surface = surface
        self._fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
        self._capacity = capacity
        self._refill_ms = max(refill_seconds, 0.001) * 1000.0
        self._max_wait = max_wait_seconds
        self._ttl_ms = int((refill_seconds * capacity + 60.0) * 1000.0)
        # Per-process fallback used only while Redis is unreachable: strictly
        # weaker (each process paces itself), but far better than no pacing.
        self._local_next_allowed: dict[str, float] = {}
        self._degraded = False

    def _key(self, endpoint: str) -> str:
        """Build the Redis key for one endpoint's bucket."""
        return f"wb:bucket:{self._surface}:{endpoint}:{self._fingerprint}"

    async def acquire(self, endpoint: str) -> None:
        """Wait until this endpoint's bucket holds a token, then take it.

        Args:
            endpoint: Request path, used as part of the bucket key.

        Raises:
            IntegrationError: When a token would take longer than
                ``max_wait_seconds`` to appear.
        """
        waited = 0.0
        while True:
            wait_ms = await self._take_token(endpoint)
            if wait_ms <= 0:
                return
            wait_seconds = wait_ms / 1000.0
            if waited + wait_seconds > self._max_wait:
                raise IntegrationError(
                    f"WildBerries rate budget for {endpoint} would need "
                    f"{waited + wait_seconds:.0f}s of queueing (cap {self._max_wait:.0f}s); "
                    "not sending the request."
                )
            logger.info(
                "Pacing WB %s %s: waiting %.1fs for a rate token.",
                self._surface,
                endpoint,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)
            waited += wait_seconds

    async def _take_token(self, endpoint: str) -> float:
        """Take a token, returning the milliseconds to wait when none is free."""
        try:
            result = await cast(
                Awaitable[Any],
                self._redis.eval(
                    _ACQUIRE_SLOT_LUA,
                    1,
                    self._key(endpoint),
                    str(self._capacity),
                    str(self._refill_ms),
                    str(self._ttl_ms),
                ),
            )
        except RedisError:
            return self._local_take_token(endpoint)
        return float(result)

    def _local_take_token(self, endpoint: str) -> float:
        """Fallback pacing while Redis is down: one request per refill, per process."""
        if not self._degraded:
            self._degraded = True
            logger.exception(
                "Redis unavailable: WB %s pacing degraded to per-process spacing.",
                self._surface,
            )
        now = time.monotonic()
        next_allowed = self._local_next_allowed.get(endpoint, 0.0)
        if now >= next_allowed:
            self._local_next_allowed[endpoint] = now + self._refill_ms / 1000.0
            return 0.0
        return (next_allowed - now) * 1000.0

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Clamp the bucket to WB's own count of what is left.

        Args:
            endpoint: Request path whose bucket this response describes.
            remaining: Value of ``x-ratelimit-remaining``, or ``None`` when WB
                did not send it (nothing to learn — the bucket is left alone).
        """
        if remaining is None:
            return
        try:
            await cast(
                Awaitable[Any],
                self._redis.eval(
                    _CLAMP_SLOTS_LUA,
                    1,
                    self._key(endpoint),
                    str(max(remaining, 0)),
                    str(self._ttl_ms),
                ),
            )
        except RedisError:
            if remaining <= 0:
                self._local_next_allowed[endpoint] = time.monotonic() + self._refill_ms / 1000.0


def analytics_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the analytics surface.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's analytics token — the bucket is per token, so
            one workspace's harvest never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="analytics",
        token=token,
        capacity=settings.wb_analytics_bucket_capacity,
        refill_seconds=settings.wb_analytics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )


def marketplace_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the marketplace (FBS) surface.

    Both FBS endpoints answered ``x-ratelimit-remaining: 20`` when measured on
    2026-08-13 — a far tighter budget than the analytics surface, and the
    harvest spends one token per enabled warehouse per run.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's marketplace token — the bucket is per token.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="marketplace",
        token=token,
        capacity=settings.wb_marketplace_bucket_capacity,
        refill_seconds=settings.wb_marketplace_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )


def search_rate_gate(settings: Settings) -> RateGate:
    """Build the pacing gate for the PUBLIC search host.

    The one gate here that paces an unauthenticated surface, so it takes no
    token: search.wb.ru meters by IP and client reputation, which every process
    on this box shares. A fixed key is the point — the interactive probe, the
    scheduled run and two sellers pressing the button must queue behind each
    other rather than each discovering the limit for itself.

    Sized meaner than any measured header (capacity 1, one slot per ~30s)
    because this edge publishes no quota and does not merely refuse an overrun:
    a burst earns an escalating anti-bot block, IP-wide. Verified 2026-08-17,
    when the probe was firing three unpaced pages per press and being refused on
    roughly every second attempt.

    Args:
        settings: Bucket parameters and the Redis DSN.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="search-public",
        # No credential to key by: the bucket mirrors WB's own per-IP metering,
        # which everything running here shares.
        token="",
        capacity=settings.wb_search_bucket_capacity,
        refill_seconds=settings.wb_search_bucket_refill_seconds,
        max_wait_seconds=settings.wb_search_max_queue_seconds,
    )
