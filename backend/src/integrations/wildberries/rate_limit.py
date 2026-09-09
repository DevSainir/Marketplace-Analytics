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
from src.core.observability.metrics import WB_RATE_LIMIT_REMAINING, WB_RATE_LIMIT_WAIT
from src.core.redis import get_redis
from src.integrations.wildberries.endpoints import endpoint_label

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
local state = redis.call('HMGET', KEYS[1], 'tokens', 'ts', 'blocked_until')
-- A penalty block is WB's own number and outranks every estimate below it:
-- while it stands no token exists, however much time has passed. Without this
-- the bucket reopened after `refill_ms` — our guess — and the request landed
-- inside a block that WB then restarted (see `penalise`).
local blocked_until = tonumber(state[3])
if blocked_until ~= nil and blocked_until > now_ms then
  return blocked_until - now_ms
end
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


#: Shut this endpoint until WB says it reopens. Called with the wait WB itself
#: demanded (`X-Ratelimit-Retry`), which is the only trustworthy number here:
#: measured on prod 2026-09-09, a 429 demanding 1594 s was followed 900 s later
#: — one local refill — by a second 429 demanding exactly 694 s, the remainder.
#:
#: `tokens` is restored to capacity as of the moment the block lifts, because
#: WB's reset IS the start of a fresh window; trickling from a refill estimate
#: would keep punishing the caller after WB had stopped.
_PENALISE_LUA = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local block_ms = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local ttl_ms = tonumber(ARGV[3])
local until_ms = now_ms + block_ms
redis.call('HSET', KEYS[1], 'tokens', capacity, 'ts', until_ms, 'blocked_until', until_ms)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return tostring(until_ms)
"""


class RateGate(Protocol):
    """A pre-flight gate a WB client passes before every HTTP attempt."""

    async def acquire(self, endpoint: str) -> None:
        """Block until this endpoint's bucket holds a token."""
        ...

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Fold WB's ``x-ratelimit-remaining`` back into the bucket."""
        ...

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Hold this endpoint shut for the wait WB itself demanded."""
        ...


class NullRateGate:
    """A gate that never waits — for surfaces with no measured bucket, and tests."""

    async def acquire(self, endpoint: str) -> None:
        """Return immediately; this surface is not paced."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Ignore WB's rate headers; nothing is being paced."""
        return

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Ignore WB's penalty; nothing is being paced."""
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
            # Recorded before the sleep, so the counter reflects a wait that is
            # happening rather than only waits that finished. A harvest wedged
            # behind an empty bucket is exactly the case where the difference
            # matters — it never reaches the line after the sleep.
            WB_RATE_LIMIT_WAIT.labels(surface=self._surface, endpoint=endpoint_label(endpoint)).inc(
                wait_seconds
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
        # WB's own count, published before it is folded into our bucket. This
        # is the leading indicator for the whole harvest: it reaches zero
        # while there is still time to react, whereas every other WB metric
        # only moves once something has already failed.
        # Templated, never raw: the marketplace surface paces
        # `/api/v3/stocks/{warehouse_id}`, so the raw path would add one series
        # per warehouse per tenant. The Redis bucket KEY keeps the raw path —
        # WB meters per real endpoint, and collapsing the key would make two
        # warehouses share one budget they do not share.
        WB_RATE_LIMIT_REMAINING.labels(
            surface=self._surface, endpoint=endpoint_label(endpoint)
        ).set(remaining)
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

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Shut this endpoint for the wait WB demanded, overriding our refill.

        ``observe`` can only clamp the bucket to empty, after which it reopens
        one ``refill_seconds`` later — a local constant that has no way of
        knowing what WB actually imposed. On the statistics surface those two
        numbers disagree badly: the refill is 15 minutes and a measured penalty
        ran to 1594 s, so the next request went out 694 s early, collected its
        own 429, and restarted the window (prod, 2026-09-09). WB states the
        remainder in ``X-Ratelimit-Retry``; this is where that number is
        believed instead of guessed at.

        Args:
            endpoint: Request path whose bucket WB has blocked.
            seconds: The wait WB demanded. Non-positive values are ignored —
                a block that has already expired is not a block.
        """
        if seconds <= 0:
            return
        block_ms = seconds * 1000.0
        # The key must outlive the block it is recording. The standing TTL is
        # sized for a refill, and a penalty can be twice that: letting the key
        # expire mid-block would restore a full bucket and send the next
        # request straight back into WB's window.
        ttl_ms = int(max(self._ttl_ms, block_ms + 60_000.0))
        try:
            await cast(
                Awaitable[Any],
                self._redis.eval(
                    _PENALISE_LUA,
                    1,
                    self._key(endpoint),
                    str(block_ms),
                    str(self._capacity),
                    str(ttl_ms),
                ),
            )
        except RedisError:
            self._local_next_allowed[endpoint] = time.monotonic() + seconds


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


def statistics_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the statistics surface's settlement report.

    Sized from a live 429 on 2026-09-07 (see the settings comment): the walk's
    pages must be at least a minute apart, and WB answers a violation with a
    fifteen-minute penalty block rather than a Retry-After the ladder could
    honour — so the request must not be sent, not merely retried.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's statistics token — the bucket is per token, so
            one seller's settlement walk never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="statistics",
        token=token,
        capacity=settings.wb_statistics_bucket_capacity,
        refill_seconds=settings.wb_statistics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_statistics_max_queue_seconds,
    )


def settlement_walk_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the settlement walk's gate — the same bucket, a longer queue.

    :func:`statistics_rate_gate` refuses rather than waits, because the request
    it guards is made inside a transaction PostgreSQL closes after 300 s idle.
    The walk takes its token BEFORE opening that transaction, so waiting is
    exactly what it should do: one week of settlement rows is worth a quarter
    of an hour, and the alternative is asking anyway and restarting WB's window.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's statistics token — the bucket is per token.

    Returns:
        A gate over the same per-endpoint bucket as
        :func:`statistics_rate_gate`, willing to queue for a full refill.
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="statistics",
        token=token,
        capacity=settings.wb_statistics_bucket_capacity,
        refill_seconds=settings.wb_statistics_bucket_refill_seconds,
        max_wait_seconds=settings.wb_statistics_walk_queue_seconds,
    )


def advertising_rate_gate(settings: Settings, *, token: str) -> RateGate:
    """Build the pacing gate for the advertising surface.

    This surface is the one with two independent consumers on the same seller
    token: the nightly harvest sweeps every campaign, and the A/B rotation
    poller reads the running tests every few minutes. The bucket lives in
    Redis, so those two share one budget instead of discovering each other
    through 429s — which is exactly what happened when the poller was probed
    against an unpaced client.

    WB's published limit for ``/adv/v3/fullstats`` is 3 requests per minute
    with a 20-second minimum interval and a burst of ONE, so the default bucket
    is one token refilling every 20s. The gate is per endpoint, so the looser
    campaign-discovery and search-cluster calls do not spend the fullstats
    budget.

    Args:
        settings: Bucket parameters and the Redis DSN.
        token: The workspace's advertising token — the bucket is per token, so
            one workspace's polling never throttles another's.

    Returns:
        A Redis-backed :class:`TokenBucketRateGate`, or :class:`NullRateGate`
        when pacing is switched off (unit tests, or no Redis available).
    """
    if not settings.wb_rate_pacing_enabled:
        return NullRateGate()
    return TokenBucketRateGate(
        get_redis(),
        surface="advertising",
        token=token,
        capacity=settings.wb_advertising_bucket_capacity,
        refill_seconds=settings.wb_advertising_bucket_refill_seconds,
        max_wait_seconds=settings.wb_analytics_max_queue_seconds,
    )
