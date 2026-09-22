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

This module is the MECHANISM: the bucket, the protocol a client passes through,
and the per-process fallback for when Redis is not there. Which WB family gets
which bucket lives next door in :mod:`surfaces`.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.observability.metrics import (
    WB_RATE_LIMIT_BLOCK,
    WB_RATE_LIMIT_REMAINING,
    WB_RATE_LIMIT_WAIT,
)
from src.integrations.wildberries.endpoints import endpoint_label
from src.integrations.wildberries.rate_limit_lua import (
    ACQUIRE_SLOT_LUA,
    CLAMP_SLOTS_LUA,
    PEEK_SLOT_LUA,
    PENALISE_LUA,
    SHARE_BLOCK_LUA,
    SHARED_BLOCK_LEFT_LUA,
)

logger = get_logger(__name__)


def _until_ms(penalise_result: Any) -> float:
    """Read the absolute block end out of what ``PENALISE_LUA`` returned.

    The script answers ``{until_ms, block_ms}`` as strings, and redis-py hands
    back bytes. Parsed here rather than at the call site so the one place that
    knows the script's shape is next to the one place that calls it.
    """
    first = penalise_result[0]
    return float(first.decode() if isinstance(first, bytes) else first)


#: How much longer than WB demanded a penalty block is served.
#:
#: Every measurement we have says WB's ``X-Ratelimit-Retry`` is the remainder
#: of a window WB is free to extend, not a promise about when it reopens: a
#: 1594 s block still had 694 s left after 900 s (2026-09-09), and a request
#: 18 minutes after a good page drew 2762 s where the published reset is 917
#: (2026-09-12/14).
#:
#: The two errors are not symmetric, which is the whole argument for a number
#: above 1. Waiting 25% longer than necessary delays one report by minutes.
#: Waiting 25% too little sends a probe into an open window, and WB answers
#: that by restarting the window longer — 28 197 s became 302 940 s that way
#: on 2026-09-17, so the cheap mistake cost four and a half days.
#:
#: 1.25 rather than something larger because the margin is the *second* line of
#: defence. The first is not probing an endpoint we have no reason to think has
#: anything new (see `probe_schedule` in the finreports tasks); a margin big
#: enough to survive bad scheduling would be admitting the schedule is bad.
_BLOCK_MARGIN = 1.25

#: Extra milliseconds the bucket key outlives the block it records.
#:
#: The key expiring is read by every caller as «no block stands», which is the
#: one state we may never enter by mistake — it is how a probe gets sent into a
#: window WB has not reopened. Five minutes on top of one full block length
#: (applied in the Lua) makes an accidental expiry take a clock error of hours
#: rather than of seconds.
_BLOCK_GRACE_MS = 300_000.0


@dataclass(frozen=True, slots=True)
class _Bucket:
    """One endpoint's bucket size, precomputed."""

    capacity: int
    refill_ms: float
    ttl_ms: int

    @classmethod
    def of(cls, capacity: int, refill_seconds: float) -> _Bucket:
        """Build a bucket from WB's published burst and interval."""
        return cls(
            capacity=capacity,
            refill_ms=max(refill_seconds, 0.001) * 1000.0,
            ttl_ms=int((refill_seconds * capacity + 60.0) * 1000.0),
        )


class RateGate(Protocol):
    """A pre-flight gate a WB client passes before every HTTP attempt."""

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        """Block until this endpoint's bucket holds a token.

        ``reserve_seconds`` makes this caller yield: it will not take a token
        that has been free for less than that, leaving the freshest slot of
        every window to work someone is waiting on.
        """
        ...

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Fold WB's ``x-ratelimit-remaining`` back into the bucket."""
        ...

    async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        """Seconds until this endpoint would let THIS caller through, 0 if now."""
        ...

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Hold this endpoint shut for the wait WB itself demanded."""
        ...


class NullRateGate:
    """A gate that never waits — for surfaces with no measured bucket, and tests."""

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        """Return immediately; this surface is not paced."""
        return

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Ignore WB's rate headers; nothing is being paced."""
        return

    async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        """Always available; this surface is not paced."""
        return 0.0

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
        endpoint_buckets: Mapping[str, tuple[int, float]] | None = None,
        shared_block: Collection[str] = (),
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
            endpoint_buckets: ``path -> (capacity, refill_seconds)`` for the
                endpoints WB meters differently from the rest of the surface.
                One surface is not one budget: WB publishes a table per
                endpoint, and sizing every path from the strictest one turns a
                cheap call into a queue. Anything unlisted keeps the surface
                default, so a new endpoint is paced conservatively rather than
                unpaced.
        """
        self._redis = redis
        self._surface = surface
        self._fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
        self._default_bucket = _Bucket.of(capacity, refill_seconds)
        self._endpoint_buckets = {
            path: _Bucket.of(*limits) for path, limits in (endpoint_buckets or {}).items()
        }
        self._max_wait = max_wait_seconds
        # Per-process fallback used only while Redis is unreachable: strictly
        # weaker (each process paces itself), but far better than no pacing.
        self._local_next_allowed: dict[str, float] = {}
        self._degraded = False
        self._shared_block = frozenset(shared_block)

    def _key(self, endpoint: str) -> str:
        """Build the Redis key for one endpoint's bucket."""
        return f"wb:bucket:{self._surface}:{endpoint}:{self._fingerprint}"

    def _shared_key(self, endpoint: str) -> str:
        """The block key shared by every token on this surface's endpoint.

        No fingerprint, on purpose: this is the one piece of state that is
        deliberately not per seller.
        """
        return f"wb:block:{self._surface}:{endpoint}"

    async def _shared_block_ms(self, endpoint: str) -> float:
        """Milliseconds this endpoint is shut for everyone, 0 when it is not.

        Fails open on a Redis error, like everything else here: a block we
        cannot read is not a block, and refusing every harvest on a cache
        outage would be failing closed on the control that exists to keep
        harvests running.
        """
        if endpoint not in self._shared_block:
            return 0.0
        try:
            result = await cast(
                Awaitable[Any],
                self._redis.eval(SHARED_BLOCK_LEFT_LUA, 1, self._shared_key(endpoint)),
            )
        except RedisError:
            return 0.0
        return max(float(result), 0.0)

    def _bucket(self, endpoint: str) -> _Bucket:
        """The bucket size WB meters this endpoint with."""
        return self._endpoint_buckets.get(endpoint, self._default_bucket)

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        """Wait until this endpoint's bucket holds a token, then take it.

        Args:
            endpoint: Request path, used as part of the bucket key.

        Raises:
            IntegrationError: When a token would take longer than
                ``max_wait_seconds`` to appear.
        """
        waited = 0.0
        while True:
            # Checked BEFORE the token is taken, so a caller refused by
            # somebody else's block does not also spend its own budget doing
            # it. The two waits are combined by `max`: our bucket and WB's
            # refusal are different constraints and both have to be satisfied.
            wait_ms = max(
                await self._shared_block_ms(endpoint),
                await self._take_token(endpoint, reserve_seconds),
            )
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

    async def _take_token(self, endpoint: str, reserve_seconds: float = 0.0) -> float:
        """Take a token, returning the milliseconds to wait when none is free."""
        bucket = self._bucket(endpoint)
        try:
            result = await cast(
                Awaitable[Any],
                self._redis.eval(
                    ACQUIRE_SLOT_LUA,
                    1,
                    self._key(endpoint),
                    str(bucket.capacity),
                    str(bucket.refill_ms),
                    str(bucket.ttl_ms),
                    str(int(reserve_seconds * 1000)),
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
            self._local_next_allowed[endpoint] = now + self._bucket(endpoint).refill_ms / 1000.0
            return 0.0
        return (next_allowed - now) * 1000.0

    async def retry_after(self, endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        """How long this endpoint stays shut for THIS caller, without spending a token.

        The question «Обновить» has to answer before it enqueues anything: the
        settlement bucket refills once every fifteen minutes, so a click soon
        after the hourly tick would otherwise queue a harvest whose first act is
        to sit still for most of a quarter of an hour. Knowing the number here
        turns that into an immediate «попробуйте через N минут».

        Read-only by construction. A peek that took a token would spend the
        harvest's budget every time somebody looked at the page, which is the
        opposite of the point.

        Args:
            endpoint: Request path whose bucket to inspect.

        Returns:
            Seconds until a request may go out; ``0.0`` when one may go now, and
            also when Redis is unreachable — an unknown block is not a block,
            and refusing a harvest on a cache outage would be failing closed on
            the one control that exists to keep harvests running.
        """
        bucket = self._bucket(endpoint)
        try:
            result = await cast(
                Awaitable[Any],
                self._redis.eval(
                    PEEK_SLOT_LUA,
                    1,
                    self._key(endpoint),
                    str(bucket.capacity),
                    str(bucket.refill_ms),
                    str(int(reserve_seconds * 1000)),
                ),
            )
        except RedisError:
            return 0.0
        return max(float(result), await self._shared_block_ms(endpoint), 0.0) / 1000.0

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
        bucket = self._bucket(endpoint)
        try:
            await cast(
                Awaitable[Any],
                self._redis.eval(
                    CLAMP_SLOTS_LUA,
                    1,
                    self._key(endpoint),
                    str(max(remaining, 0)),
                    str(bucket.ttl_ms),
                ),
            )
        except RedisError:
            if remaining <= 0:
                self._local_next_allowed[endpoint] = time.monotonic() + bucket.refill_ms / 1000.0

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Shut this endpoint for longer than the wait WB demanded.

        ``observe`` can only clamp the bucket to empty, after which it reopens
        one ``refill_seconds`` later — a local constant that has no way of
        knowing what WB actually imposed. On the statistics surface those two
        numbers disagree badly: the refill is 15 minutes and a measured penalty
        ran to 1594 s, so the next request went out 694 s early, collected its
        own 429, and restarted the window (prod, 2026-09-09).

        WB states the remainder in ``X-Ratelimit-Retry``, and this is where
        that number is believed **as a floor** rather than as the truth. The
        distinction is what the 2026-09-17 escalation was made of: three
        successive blocks of 28 197, 18 624 and 302 940 s, each one served
        exactly as long as WB said and each one followed by a probe that WB
        answered with a longer block. Serving what WB says is what our state
        said was safe; every measurement we have says otherwise.

        So the demanded wait is multiplied by :data:`_BLOCK_MARGIN`, and a
        refusal arriving with no block of ours standing doubles the last block
        instead — see :data:`~src.integrations.wildberries.rate_limit_lua.PENALISE_LUA`,
        which holds that arithmetic so it is atomic with the write.

        Args:
            endpoint: Request path whose bucket WB has blocked.
            seconds: The wait WB demanded. Non-positive values are ignored —
                a block that has already expired is not a block.
        """
        if seconds <= 0:
            return
        # WB's own number, before our margin. The metric describes WB; the
        # margin is our policy and would make the series describe us.
        WB_RATE_LIMIT_BLOCK.labels(
            surface=self._surface, endpoint=endpoint_label(endpoint)
        ).observe(seconds)
        bucket = self._bucket(endpoint)
        try:
            result = await cast(
                Awaitable[Any],
                self._redis.eval(
                    PENALISE_LUA,
                    1,
                    self._key(endpoint),
                    str(seconds * 1000.0),
                    str(bucket.capacity),
                    str(_BLOCK_GRACE_MS),
                    str(_BLOCK_MARGIN),
                ),
            )
            if endpoint in self._shared_block:
                # The same instant, written where every other token will see
                # it. Without this the fleet walk earns the block once per
                # seller: it is sequential, so seller 2 is refused a minute
                # after seller 1 was, knowing nothing about it — which is what
                # five countdowns 0.77 s apart looked like on 2026-09-17.
                await cast(
                    Awaitable[Any],
                    self._redis.eval(
                        SHARE_BLOCK_LUA,
                        1,
                        self._shared_key(endpoint),
                        str(_until_ms(result)),
                        str(_BLOCK_GRACE_MS),
                    ),
                )
        except RedisError:
            self._local_next_allowed[endpoint] = time.monotonic() + seconds * _BLOCK_MARGIN
