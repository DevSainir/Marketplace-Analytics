"""Integration tests for the two Redis-backed security primitives.

Both are documented as **failing open** — a Redis outage must degrade the
control, never block authenticated traffic — and that policy is only real if it
is exercised against a client that can actually fail. These tests use a live
Redis on the throwaway test index, then simulate an outage by pointing the
module at a dead endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import Request

from src.core.exceptions import RateLimitError
from src.core.ratelimit import RateLimiter
from src.core.redis import mark_user_sessions_revoked, sessions_revoked_after


def _request(client_ip: str = "203.0.113.7") -> Request:
    """Build a minimal ASGI request carrying a client address.

    Args:
        client_ip: The peer address the limiter keys its counter on.

    Returns:
        A request object with just the scope fields the limiter reads.
    """
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/login",
            "headers": [],
            "client": (client_ip, 51234),
        }
    )


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
async def test_requests_inside_the_budget_pass(redis_client: Any) -> None:
    """The limiter is silent until the budget is actually spent."""
    limiter = RateLimiter(scope="test-auth", limit=3, window_seconds=60)

    for _ in range(3):
        await limiter(_request())


async def test_the_request_after_the_budget_is_rejected(redis_client: Any) -> None:
    """Attempt N+1 raises ``RateLimitError`` (a 429 at the transport edge)."""
    limiter = RateLimiter(scope="test-auth", limit=3, window_seconds=60)
    for _ in range(3):
        await limiter(_request())

    with pytest.raises(RateLimitError):
        await limiter(_request())


async def test_each_client_ip_gets_its_own_budget(redis_client: Any) -> None:
    """One abusive client must not lock everyone else out.

    A shared counter would turn a single credential-stuffing bot into a global
    denial of service against the login form.
    """
    limiter = RateLimiter(scope="test-auth", limit=2, window_seconds=60)
    for _ in range(2):
        await limiter(_request("198.51.100.1"))

    await limiter(_request("198.51.100.2"))


async def test_separate_scopes_do_not_share_a_budget(redis_client: Any) -> None:
    """``/refresh`` has its own budget so silent refreshes cannot starve logins.

    The SPA refreshes on every page load; sharing the login budget bounced real
    sessions to the login screen, which is why the scopes are split.
    """
    login = RateLimiter(scope="auth", limit=2, window_seconds=60)
    refresh = RateLimiter(scope="auth-refresh", limit=2, window_seconds=60)
    for _ in range(2):
        await login(_request())

    await refresh(_request())


async def test_the_counter_expires_with_the_window(redis_client: Any) -> None:
    """The window is enforced by a TTL, so the budget genuinely resets.

    Without the ``EXPIRE`` the first burst would ban that IP permanently.
    """
    limiter = RateLimiter(scope="test-auth", limit=1, window_seconds=45)
    await limiter(_request("203.0.113.99"))

    ttl = await redis_client.ttl("ratelimit:test-auth:203.0.113.99")

    assert 0 < ttl <= 45


async def test_the_limiter_fails_open_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis outage must not take the login endpoint down with it.

    The limiter is abuse damping, not a correctness guarantee; refusing every
    request during a cache outage would be a worse failure than allowing them.
    """
    from redis.asyncio import Redis

    from src.core import ratelimit

    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.05)
    monkeypatch.setattr(ratelimit, "get_redis", lambda: dead)
    limiter = RateLimiter(scope="test-auth", limit=1, window_seconds=60)

    for _ in range(5):
        await limiter(_request())

    await dead.aclose()


# --------------------------------------------------------------------------- #
# Session revocation watermark
# --------------------------------------------------------------------------- #
async def test_no_watermark_means_no_revocation(redis_client: Any) -> None:
    """An untouched account reports ``None`` — every token stays valid."""
    assert await sessions_revoked_after(uuid.uuid4()) is None


async def test_marking_a_user_records_a_revocation_instant(redis_client: Any) -> None:
    """The watermark is a UTC instant, comparable to a token's ``iat``."""
    user_id = uuid.uuid4()
    before = datetime.now(UTC) - timedelta(seconds=1)

    await mark_user_sessions_revoked(user_id)

    watermark = await sessions_revoked_after(user_id)
    assert watermark is not None
    assert watermark >= before


async def test_the_watermark_is_scoped_to_one_user(redis_client: Any) -> None:
    """Revoking one account must not log everyone else out."""
    revoked, untouched = uuid.uuid4(), uuid.uuid4()

    await mark_user_sessions_revoked(revoked)

    assert await sessions_revoked_after(revoked) is not None
    assert await sessions_revoked_after(untouched) is None


async def test_the_watermark_outlives_any_outstanding_access_token(
    redis_client: Any,
) -> None:
    """Its TTL exceeds the access TTL, so no live token can outlast the check.

    A shorter TTL would let a stolen token become valid again once the key
    expired — the exact window the watermark exists to close.
    """
    from src.core.config import settings

    user_id = uuid.uuid4()

    await mark_user_sessions_revoked(user_id)

    ttl = await redis_client.ttl(f"auth:revoked-after:{user_id}")
    assert ttl > settings.access_token_ttl_seconds


async def test_a_corrupt_watermark_is_ignored_rather_than_crashing(
    redis_client: Any,
) -> None:
    """Unparseable cache content degrades to "no revocation", not a 500.

    Every authenticated request reads this key; a poisoned value must not take
    the whole API down.
    """
    user_id = uuid.uuid4()
    await redis_client.set(f"auth:revoked-after:{user_id}", "not-a-timestamp")

    assert await sessions_revoked_after(user_id) is None


async def test_revocation_check_fails_open_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An outage widens the revocation window instead of blocking all traffic.

    The documented trade-off: revocation degrades to the 15-minute access TTL
    rather than every authenticated request failing.
    """
    from redis.asyncio import Redis

    from src.core import redis as core_redis

    dead = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.05)
    monkeypatch.setattr(core_redis, "_redis", dead)

    assert await sessions_revoked_after(uuid.uuid4()) is None

    await dead.aclose()
