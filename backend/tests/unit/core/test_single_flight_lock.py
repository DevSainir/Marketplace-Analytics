"""Unit tests for the cross-process single-flight lock.

The lock exists to stop an hourly beat entry from starting a second copy of a
job that is still running. Its three ways of being wrong all end in the same
place — two harvests spending each other's WB request budget — so each is
pinned here:

* a second caller must be turned away while the first holds it,
* the lock must be released on the way out (including on an exception), or the
  job stops running until the TTL expires,
* a release must not delete a lock the caller no longer owns.

The fourth property is the opposite of the others: when Redis itself is down the
caller must still run. A job that silently stops happening because the cache is
unavailable is precisely the failure this module was added to prevent.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from redis.exceptions import RedisError

from src.core.locks import single_flight

pytestmark = pytest.mark.unit


class _FakeRedis:
    """A tiny async stand-in supporting only ``SET NX EX`` and the release Lua."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        key, token = args[0], args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _BrokenRedis:
    """A client whose every call fails, standing in for a Redis outage."""

    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
    ) -> bool | None:
        raise RedisError("connection refused")

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        raise RedisError("connection refused")


async def test_a_second_caller_is_turned_away_while_the_first_holds_the_lock() -> None:
    """Arrange a held lock; the concurrent caller must be told to stand down."""
    redis = _FakeRedis()

    async with (
        single_flight("job", ttl_seconds=60, redis=redis) as first,
        single_flight("job", ttl_seconds=60, redis=redis) as second,
    ):
        assert first is True
        assert second is False


async def test_the_lock_is_released_when_the_block_finishes() -> None:
    """The next tick must be able to run — otherwise the job stalls to the TTL."""
    redis = _FakeRedis()

    async with single_flight("job", ttl_seconds=60, redis=redis):
        pass

    async with single_flight("job", ttl_seconds=60, redis=redis) as acquired:
        assert acquired is True
    assert redis.store == {}


async def test_the_lock_is_released_when_the_body_raises() -> None:
    """A harvest that dies mid-walk must not block every later run."""
    redis = _FakeRedis()

    with pytest.raises(RuntimeError):
        async with single_flight("job", ttl_seconds=60, redis=redis):
            raise RuntimeError("harvest blew up")

    assert redis.store == {}


async def test_a_caller_that_lost_the_lock_does_not_delete_the_new_holders() -> None:
    """An overrunning run must not free the lock of the run that replaced it.

    Without the token comparison this is worse than no lock at all: it unguards
    the job at exactly the moment it is already running long.
    """
    redis = _FakeRedis()

    async with single_flight("job", ttl_seconds=60, redis=redis):
        # The TTL lapses mid-run and the next tick takes the lock for itself.
        redis.store["job"] = "the-next-runs-token"

    assert redis.store == {"job": "the-next-runs-token"}


async def test_an_unreachable_redis_lets_the_caller_run() -> None:
    """Fail open: a cache outage must not silently stop a scheduled job."""
    async with single_flight("job", ttl_seconds=60, redis=_BrokenRedis()) as acquired:
        assert acquired is True


async def test_a_failed_release_does_not_propagate() -> None:
    """Redis dying *during* the job must not turn a good run into a failure."""

    class _FailsOnRelease(_FakeRedis):
        async def eval(self, script: str, numkeys: int, *args: str) -> int:
            raise RedisError("gone away")

    async with single_flight("job", ttl_seconds=60, redis=_FailsOnRelease()) as acquired:
        assert acquired is True


class _ExpiringRedis(_FakeRedis):
    """A fake with real, wall-clock key expiry.

    Real time rather than a fake clock on purpose: the heartbeat sleeps on the
    event loop, so a test that fakes the clock proves nothing about whether it
    actually fires. The TTLs below are therefore fractions of a second, and the
    tests wait them out for real.
    """

    def __init__(self) -> None:
        super().__init__()
        self.expiry: dict[str, float] = {}
        self.renewals = 0

    def _expire_due(self) -> None:
        now = time.monotonic()
        for key, at in list(self.expiry.items()):
            if at <= now:
                self.store.pop(key, None)
                self.expiry.pop(key, None)

    async def set(
        self, key: str, value: str, *, nx: bool = False, px: int | None = None
    ) -> bool | None:
        self._expire_due()
        if nx and key in self.store:
            return None
        self.store[key] = value
        if px is not None:
            self.expiry[key] = time.monotonic() + px / 1000
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        self._expire_due()
        key, token = args[0], args[1]
        if self.store.get(key) != token:
            return 0
        if "expire" in script:
            self.renewals += 1
            self.expiry[key] = time.monotonic() + float(args[2]) / 1000
            return 1
        del self.store[key]
        self.expiry.pop(key, None)
        return 1


#: One TTL, in seconds. Small enough to wait out several times in a unit test.
TTL = 0.3


async def test_a_live_holder_keeps_the_lock_past_its_ttl() -> None:
    """The heartbeat is what holds the lock — a long run must not lose it.

    Without renewal, sizing the TTL is a bet on the slowest run: lose that bet
    and a second harvest joins the first mid-walk, on WB surfaces that allow one
    request a minute between them.
    """
    redis = _ExpiringRedis()

    async with single_flight("job", ttl_seconds=TTL, redis=redis) as acquired:
        assert acquired is True
        await asyncio.sleep(TTL * 3)
        # Three TTLs in, the lock is still ours — and still refuses a rival.
        async with single_flight("job", ttl_seconds=TTL, redis=redis) as rival:
            assert rival is False

    assert redis.renewals >= 3


async def test_a_dead_holder_lets_go_within_one_ttl() -> None:
    """The other half: a killed process must not strand the job.

    This is the case that costs a harvest: an hour of TTL left behind by a
    holder the OOM killer took, or by a deploy recreating the worker.
    A holder that never renews is exactly a holder that died.
    """
    redis = _ExpiringRedis()
    await redis.set("job", "dead-holders-token", nx=True, px=int(TTL * 1000))

    await asyncio.sleep(TTL * 1.5)

    async with single_flight("job", ttl_seconds=TTL, redis=redis) as acquired:
        assert acquired is True


async def test_the_heartbeat_stops_when_the_block_exits() -> None:
    """A leaked renewal task would hold a lock nobody is using."""
    redis = _ExpiringRedis()

    async with single_flight("job", ttl_seconds=TTL, redis=redis):
        await asyncio.sleep(TTL)
    renewals_at_exit = redis.renewals
    await asyncio.sleep(TTL * 2)

    assert redis.renewals == renewals_at_exit
    assert redis.store == {}


async def test_a_renewal_failure_does_not_kill_the_guarded_work() -> None:
    """Redis hiccuping mid-run must not raise into the harvest."""

    class _FlakyRenewals(_ExpiringRedis):
        async def eval(self, script: str, numkeys: int, *args: str) -> int:
            if "expire" in script:
                raise RedisError("blip")
            return await super().eval(script, numkeys, *args)

    redis = _FlakyRenewals()

    async with single_flight("job", ttl_seconds=TTL, redis=redis) as acquired:
        await asyncio.sleep(TTL * 1.5)
        assert acquired is True
