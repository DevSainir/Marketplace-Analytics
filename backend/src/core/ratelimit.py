"""Redis-backed fixed-window rate limiting for abuse-prone endpoints.

Implemented as a FastAPI dependency so individual routers opt in explicitly
(the auth surface: register / login / refresh). Uses the shared Redis client
from :mod:`src.core.redis` — no extra dependency, and counters are shared
across API replicas.

Availability policy: fails open on Redis outages — the limiter is an abuse
dampener, not a correctness guarantee. The outage is reported to
:mod:`src.core.degradation` rather than logged from here, so that one Redis
failure raises one alertable event instead of one traceback per request, and so
that something above this module can notice when session revocation is failing
open at the same time (register P1.2).
"""

from __future__ import annotations

from fastapi import Request

from src.core.client_ip import resolve_client_ip
from src.core.degradation import CONTROL_AUTH_RATE_LIMIT, report_degraded, report_healthy
from src.core.exceptions import RateLimitError
from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)


class RateLimiter:
    """Per-client-IP fixed-window counter usable as a route dependency.

    The key comes from :func:`~src.core.client_ip.resolve_client_ip`, which
    reads the address nginx wrote and never one the client supplied. That
    distinction is the control: keying on ``request.client.host`` let anyone
    reset their own counter with a made-up ``X-Forwarded-For``, since uvicorn
    runs in always-trust mode and takes the leftmost entry of ``X-Forwarded-For``,
    which nginx then appended to rather than replaced. nginx no longer forwards
    that chain at all, but this must not depend on it: either layer alone has to
    close the hole.

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
            request: The incoming request; the resolved client IP forms the key.

        Raises:
            RateLimitError: When the client exceeded the window budget (429).
        """
        client_ip = resolve_client_ip(request)
        within_budget = await consume_budget(
            scope=self._scope,
            subject=client_ip,
            limit=self._limit,
            window_seconds=self._window,
        )
        if not within_budget:
            raise RateLimitError("Слишком много запросов. Попробуйте позже.")


async def consume_budget(*, scope: str, subject: str, limit: int, window_seconds: int) -> bool:
    """Count one use of a fixed-window budget and report whether it fitted.

    The counting half of :class:`RateLimiter`, separated so a caller that keys
    on something other than the client address can reuse it. The rate limiter
    keys on the IP; the «Обновить» enqueue guard keys on the workspace, because
    the resource it protects — the Celery queue and the WB budget behind it — is
    spent per tenant, and a tenant is not one address.

    It lives here rather than in a module because ``src.core`` may not import a
    business module; the module supplies the subject and owns the decision about
    what to do when the answer is ``False``.

    Args:
        scope: Key namespace; callers sharing one share a budget.
        subject: What the budget is counted against (an IP, a workspace id).
        limit: Maximum uses per window.
        window_seconds: Fixed window length.

    Returns:
        ``True`` when this use fitted inside the budget — including when Redis
        is unreachable, matching this module's fail-open policy.
    """
    key = f"ratelimit:{scope}:{subject}"
    try:
        redis = get_redis()
        current = await redis.incr(key)
        if current == 1:
            # First hit opens the window; EXPIRE is separate from INCR but
            # a lost expiry (crash in between) only widens one window.
            await redis.expire(key, window_seconds)
    except Exception as exc:
        report_degraded(CONTROL_AUTH_RATE_LIMIT, detail=f"{type(exc).__name__}: {exc}")
        return True
    report_healthy(CONTROL_AUTH_RATE_LIMIT)
    if current > limit:
        logger.warning(
            "Budget exceeded on '%s' by %s (%d/%d in %ds).",
            scope,
            subject,
            current,
            limit,
            window_seconds,
        )
        return False
    return True
