"""Shared async Redis client and security-critical Redis-backed primitives.

Owns the process-wide :class:`redis.asyncio.Redis` connection pool (mirroring
how :mod:`src.core.database` owns the SQLAlchemy engine) plus the per-user
session-revocation watermark used to make "log out everywhere" apply to
already-issued access tokens, not just refresh tokens.

Availability policy: both helpers **fail open** on Redis outages. Blocking all
authenticated traffic because the cache is down is a worse failure mode than
temporarily widening the revocation window back to the access-token TTL; every
degradation is logged loudly so it cannot pass unnoticed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)

# Single client (and therefore one connection pool) per process, shared by the
# rate limiter and the revocation watermark. ``decode_responses`` keeps the
# API str-in/str-out.
_redis: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Redis:
    """Return the process-wide shared async Redis client."""
    return _redis


async def close_redis() -> None:
    """Close the shared client's connection pool on application shutdown."""
    await _redis.aclose()


def _revocation_key(user_id: uuid.UUID) -> str:
    """Build the per-user revocation-watermark key."""
    return f"auth:revoked-after:{user_id}"


async def mark_user_sessions_revoked(user_id: uuid.UUID) -> None:
    """Record a revocation watermark invalidating all previously issued tokens.

    Any access token whose ``iat`` predates this moment is rejected by
    :func:`sessions_revoked_after` checks in the auth dependency. The key only
    needs to outlive the longest possible outstanding access token, so it
    expires after the access TTL (plus a small clock-skew margin).

    Args:
        user_id: The user whose entire session set must be invalidated.
    """
    key = _revocation_key(user_id)
    ttl = settings.access_token_ttl_seconds + 60
    try:
        await _redis.set(key, str(datetime.now(UTC).timestamp()), ex=ttl)
    except RedisError:
        logger.exception(
            "Redis unavailable: could not write session-revocation watermark for user %s; "
            "outstanding access tokens will survive until natural expiry.",
            user_id,
        )


async def sessions_revoked_after(user_id: uuid.UUID) -> datetime | None:
    """Return the user's revocation watermark, or ``None`` when unset.

    Args:
        user_id: The authenticated principal being checked.

    Returns:
        The UTC instant before which all issued tokens are invalid, or ``None``
        when no revocation is in force (or Redis is unreachable — fail open).
    """
    try:
        raw = await _redis.get(_revocation_key(user_id))
    except RedisError:
        logger.exception(
            "Redis unavailable: skipping session-revocation check for user %s.", user_id
        )
        return None
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError):
        logger.error("Corrupt revocation watermark for user %s: %r", user_id, raw)
        return None
