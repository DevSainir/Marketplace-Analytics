"""Redis-backed fixed-window rate limiting for abuse-prone endpoints.

Implemented as a FastAPI dependency so individual routers opt in explicitly
(the auth surface: register / login / refresh). Uses the shared Redis client
from :mod:`src.core.redis` — no extra dependency, and counters are shared
across API replicas.

Availability policy: fails open on Redis outages (with a loud log) — the
limiter is an abuse dampener, not a correctness guarantee.
"""

from __future__ import annotations

from fastapi import Request

from src.core.exceptions import RateLimitError
from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)


class RateLimiter:
    """Per-client-IP fixed-window counter usable as a route dependency.

    The key is the immediate peer address. Behind a reverse proxy every client
    shares the proxy's address, so deployments with a proxy must either
    terminate abuse there or run uvicorn with ``--proxy-headers`` so
    ``request.client`` reflects ``X-Forwarded-For`` from the trusted hop.
    ``X-Forwarded-For`` is deliberately not read here: unauthenticated clients
    can spoof it to dodge the limiter.

    Args:
        scope: Short key namespace identifying the protected surface
            (e.g. ``"auth"``); endpoints sharing a scope share their budget.
        limit: Maximum requests allowed per window.
        window_seconds: Fixed window length in seconds.
    """

    def __init__(self, *, scope: str, limit: int, window_seconds: int) -> None:
        """Store the limiter configuration for this dependency instance."""
        self._scope = scope
        self._limit = limit
        self._window = window_seconds

    async def __call__(self, request: Request) -> None:
        """Count this request and reject it once the window budget is spent.

        Args:
            request: The incoming request; the peer IP forms the counter key.

        Raises:
            RateLimitError: When the client exceeded the window budget (429).
        """
        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{self._scope}:{client_ip}"
        try:
            redis = get_redis()
            current = await redis.incr(key)
            if current == 1:
                # First hit opens the window; EXPIRE is separate from INCR but
                # a lost expiry (crash in between) only widens one window.
                await redis.expire(key, self._window)
        except Exception:
            logger.exception("Redis unavailable: rate limiter '%s' failing open.", self._scope)
            return
        if current > self._limit:
            logger.warning(
                "Rate limit exceeded on '%s' by %s (%d/%d in %ds).",
                self._scope,
                client_ip,
                current,
                self._limit,
                self._window,
            )
            raise RateLimitError("Too many requests. Please retry later.")
