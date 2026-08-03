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


async def drain_redis_pool() -> None:
    """Disconnect every pooled connection while leaving the client reusable.

    The Redis client above is process-wide, and ``redis.asyncio`` binds each
    pooled connection to the event loop that opened it — exactly like asyncpg
    behind the SQLAlchemy engine. A Celery task runs its own short-lived
    ``asyncio.run`` loop, so a task that returns while leaving a connection in
    the pool hands the *next* task a socket whose transport belongs to a loop
    that no longer exists. The next task's first Redis call then dies with
    ``RuntimeError: Event loop is closed`` before doing any work.

    That is not hypothetical: it silently voided the ``sales-funnel`` source of
    every ``monitoring.harvest_sku_window`` after the worker's first task,
    because the funnel's rate-gate ``acquire`` is the first Redis op in the
    harvest and the gate only catches :class:`RedisError`, not this
    ``RuntimeError`` — so «Обновить все SKU» kept succeeding with
    ``funnel_rows: 0``. See :func:`src.core.tasks.run_task`, which drains this
    pool alongside the engine at every task boundary.

    Draining rather than closing keeps the singleton reusable: the pool object
    stays, and the next command lazily reconnects on the current loop.
    """
    await _redis.connection_pool.disconnect()


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
