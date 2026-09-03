"""Rate-limit budgets and the refresh-cookie writer, shared by both route halves.

Extracted when `routers.py` reached the 500-line ceiling and became this
package. It exists so `recovery.py` can open a session without importing from
`__init__`, which imports it back.
"""

from __future__ import annotations

from fastapi import Depends, Response

from src.core.config import settings
from src.core.ratelimit import RateLimiter
from src.modules.users.schemas import IssuedTokens

# One shared per-IP budget across /login + /register: it damps credential
# stuffing and invite guessing (each of which also burns a bcrypt cycle
# server-side).
_auth_rate_limit = Depends(
    RateLimiter(
        scope="auth",
        limit=settings.auth_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
)

# /refresh has its own, looser budget: its secret is an unguessable random
# cookie (not a password), and the SPA calls it silently on every page load
# and ~every 14 minutes per tab — sharing the login budget starved legitimate
# sessions into 429s, which the frontend read as "logged out".
_refresh_rate_limit = Depends(
    RateLimiter(
        scope="auth-refresh",
        limit=settings.refresh_rate_limit_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
)


# The recovery surface gets its OWN, tighter budget rather than sharing the
# login one. Every endpoint behind it either sends an email or spends a guess
# against a six-digit code, so the thing being rationed is different: mail a
# stranger cannot stop receiving, and attempts against a small keyspace. Five a
# minute per address is far above anyone who has actually lost a password.
_recovery_rate_limit = Depends(
    RateLimiter(
        scope="auth-recovery",
        limit=5,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
)


def _set_refresh_cookie(response: Response, tokens: IssuedTokens) -> None:
    """Attach the rotated refresh secret as a hardened HttpOnly cookie."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_secret,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=settings.refresh_cookie_path,
    )
