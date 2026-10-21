"""Unit tests for the per-account login backoff.

The control exists because the per-IP throttle is the wrong shape for credential
stuffing: a campaign spread over thousands of rented addresses stays inside
every per-address budget while hammering one account after another. What has to
be bounded is attempts *against an account*, and these cases pin that bound —
the schedule, the reset, and the two failure modes that would quietly undo it
(a Redis outage locking everyone out, or the counter surviving a success).

The key-shape case is here too. Redis persists into an AOF volume the backups
include, and a plaintext key per attacked address would turn that volume into a
customer list.
"""

from __future__ import annotations

from redis.exceptions import RedisError

from src.modules.users.services.lockout import LoginBackoff

EMAIL = "victim@example.com"


class FakeRedis:
    """The slice of the Redis surface this control uses, in a dict."""

    def __init__(self) -> None:
        """Start empty."""
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        """Increment a counter, starting from zero."""
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def expire(self, key: str, seconds: int) -> bool:
        """Record a TTL without enforcing it."""
        self.expiries[key] = seconds
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        """Store a value, remembering any TTL."""
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        """Return a stored value, or ``None``."""
        return self.values.get(key)

    async def delete(self, key: str) -> int:
        """Drop a key, reporting how many were removed."""
        self.expiries.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0


class DeadRedis:
    """A Redis that is down, the way an outage presents to this control."""

    async def incr(self, key: str) -> int:
        """Fail like a severed connection."""
        raise RedisError("Connection refused")

    async def expire(self, key: str, seconds: int) -> bool:
        """Fail like a severed connection."""
        raise RedisError("Connection refused")

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        """Fail like a severed connection."""
        raise RedisError("Connection refused")

    async def get(self, key: str) -> str | None:
        """Fail like a severed connection."""
        raise RedisError("Connection refused")

    async def delete(self, key: str) -> int:
        """Fail like a severed connection."""
        raise RedisError("Connection refused")


def _use(monkeypatch, store: object) -> None:
    """Point the single Redis accessor at a stand-in."""
    from src.core import redis as core_redis

    monkeypatch.setattr(core_redis, "_redis", store)


async def test_a_few_failures_cost_nothing(monkeypatch) -> None:
    """Mistyping a password twice must not punish an ordinary person."""
    # Arrange
    _use(monkeypatch, FakeRedis())
    backoff = LoginBackoff(threshold=5, base_seconds=30, max_seconds=900)

    # Act
    for _ in range(4):
        await backoff.record_failure(email=EMAIL)

    # Assert
    assert await backoff.penalty_remaining(email=EMAIL) == 0


async def test_the_penalty_starts_at_the_threshold_and_doubles(monkeypatch) -> None:
    """Each further miss costs twice the last — the attacker's budget, not ours."""
    # Arrange
    _use(monkeypatch, FakeRedis())
    backoff = LoginBackoff(threshold=5, base_seconds=30, max_seconds=900)
    observed: list[int] = []

    # Act
    for _ in range(8):
        await backoff.record_failure(email=EMAIL)
        observed.append(await backoff.penalty_remaining(email=EMAIL))

    # Assert. Rounded down by a second of elapsed wall clock, hence the range.
    assert observed[:4] == [0, 0, 0, 0]
    assert 29 <= observed[4] <= 30
    assert 59 <= observed[5] <= 60
    assert 119 <= observed[6] <= 120
    assert 239 <= observed[7] <= 240


async def test_the_penalty_is_capped(monkeypatch) -> None:
    """The ceiling is what keeps a triggered backoff a nuisance, not a takeover."""
    # Arrange
    _use(monkeypatch, FakeRedis())
    backoff = LoginBackoff(threshold=5, base_seconds=30, max_seconds=900)

    # Act
    for _ in range(30):
        await backoff.record_failure(email=EMAIL)

    # Assert
    assert 899 <= await backoff.penalty_remaining(email=EMAIL) <= 900


async def test_a_success_clears_the_run(monkeypatch) -> None:
    """Consecutive means consecutive: one success resets the schedule."""
    # Arrange
    _use(monkeypatch, FakeRedis())
    backoff = LoginBackoff(threshold=5, base_seconds=30, max_seconds=900)
    for _ in range(6):
        await backoff.record_failure(email=EMAIL)

    # Act
    await backoff.clear(email=EMAIL)

    # Assert
    assert await backoff.penalty_remaining(email=EMAIL) == 0
    await backoff.record_failure(email=EMAIL)
    assert await backoff.penalty_remaining(email=EMAIL) == 0


async def test_accounts_are_counted_separately(monkeypatch) -> None:
    """One attacked account must not back off every other customer."""
    # Arrange
    _use(monkeypatch, FakeRedis())
    backoff = LoginBackoff(threshold=5, base_seconds=30, max_seconds=900)

    # Act
    for _ in range(10):
        await backoff.record_failure(email=EMAIL)

    # Assert
    assert await backoff.penalty_remaining(email="someone-else@example.com") == 0


async def test_the_account_address_never_reaches_a_redis_key(monkeypatch) -> None:
    """The AOF volume goes into backups; it must not become a customer list."""
    # Arrange
    store = FakeRedis()
    _use(monkeypatch, store)
    backoff = LoginBackoff(threshold=1, base_seconds=30, max_seconds=900)

    # Act
    await backoff.record_failure(email=EMAIL)

    # Assert
    assert store.values, "the test would pass vacuously if nothing were written"
    for key in store.values:
        assert EMAIL not in key
        assert "victim" not in key


async def test_a_redis_outage_lets_everyone_in_rather_than_nobody(monkeypatch) -> None:
    """Fail open, like every other Redis-backed control here."""
    # Arrange
    _use(monkeypatch, DeadRedis())
    backoff = LoginBackoff(threshold=1, base_seconds=30, max_seconds=900)

    # Act
    await backoff.record_failure(email=EMAIL)
    penalty = await backoff.penalty_remaining(email=EMAIL)
    await backoff.clear(email=EMAIL)

    # Assert
    assert penalty == 0


async def test_a_corrupt_stored_penalty_does_not_lock_the_account(monkeypatch) -> None:
    """Garbage in the store must decay to "no penalty", never to a hard block."""
    # Arrange
    store = FakeRedis()
    _use(monkeypatch, store)
    # threshold=1 so a block key actually exists to corrupt; with the default
    # this test would pass without ever exercising the parse.
    backoff = LoginBackoff(threshold=1)
    await backoff.record_failure(email=EMAIL)
    corrupted = [k for k in store.values if "login-block" in k]
    assert corrupted, "nothing was blocked, so there is nothing to corrupt"
    for key in corrupted:
        store.values[key] = "not-a-timestamp"

    # Act
    penalty = await backoff.penalty_remaining(email=EMAIL)

    # Assert
    assert penalty == 0
