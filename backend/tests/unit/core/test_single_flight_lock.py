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

import pytest
from redis.exceptions import RedisError

from src.core.locks import single_flight

pytestmark = pytest.mark.unit


class _FakeRedis:
    """A tiny async stand-in supporting only ``SET NX EX`` and the release Lua."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
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
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
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
