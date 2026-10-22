"""Shared async Redis client and security-critical Redis-backed primitives.

Owns the :class:`redis.asyncio.Redis` connection pool — one per event loop, see
:func:`get_redis` (mirroring how :mod:`src.core.database` owns the SQLAlchemy
engine) — plus the two
session-revocation watermarks that make revocation apply to already-issued
access tokens rather than only to refresh rows.

**There are two, and the difference between them is the whole point.** The
per-*user* watermark ends everything that account has open — the incident lever,
"log out everywhere". The per-*family* watermark ends one login lineage: this
browser, or the one whose refresh token was replayed. Using the user key for a
family-scoped act was never an option — it would sign a customer's colleagues
and their own phone out because one tab was closed — and its absence is why
logout left the caller's access token alive for up to fifteen minutes.
Same mechanism, correct blast radius.

Availability policy: both helpers **fail open** on Redis outages. Blocking all
authenticated traffic because the cache is down is a worse failure mode than
temporarily widening the revocation window back to the access-token TTL. The
degradation is reported to :mod:`src.core.degradation`, which raises one
alertable event per outage rather than one traceback per request, and which is
the only thing positioned to notice that the auth rate limiter went down in the
same instant.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.core.config import settings
from src.core.degradation import (
    CONTROL_SESSION_REVOCATION,
    report_degraded,
    report_healthy,
)
from src.core.logging import get_logger

logger = get_logger(__name__)

# One client — and therefore one connection pool — per EVENT LOOP, shared by
# every Redis-backed control running on it. ``decode_responses`` keeps the API
# str-in/str-out.
#
# Per loop, not per process, because a ``redis.asyncio`` pool belongs to a loop
# in two ways. Each pooled socket is bound to the loop that opened it, which
# :func:`drain_redis_pool` handles at every task boundary. And the pool guards
# handing out connections with an ``asyncio.Lock``, which binds itself to the
# first loop that ever has to WAIT on it — two commands at the same instant — and
# which no drain resets. A Celery worker runs every task on a fresh
# ``asyncio.run`` loop, so with one client per process, the first task that
# contended bound the lock and every later task in that process that contended
# died with ``<asyncio.locks.Lock …> is bound to a different event loop``. That
# emptied one workspace's price snapshot for 2026-09-27: the finance tick harvests
# three sellers at once and bound it, and the monitoring harvest's sources reach
# their rate buckets together. A client per loop has nothing to carry over, so
# the number or the concurrency of tasks no longer matters. The API runs on one
# loop and keeps one client, as before.
# ``tests/unit/core/test_redis_client_per_loop.py`` holds the rule and
# ``tests/integration/celery/test_redis_loop_isolation.py`` the failure itself.
#
# **Read it only through :func:`get_redis`, including inside this module.** That
# is not style: because callers invoke the function rather than capture the
# client, the function body is the one place the process resolves "which Redis".
# ``_redis`` is the seam: ``None`` in the running app, and a test that sets it
# redirects every caller on every loop at once. Reach past it —
# ``await _client.set(...)`` in a helper down the file — and that helper
# silently opts out of the swap.
#
# It has cost real time twice. Both the replay-grace store and "log out
# everywhere" reached a live Redis from the component tier, which forbids it,
# and neither failed honestly: they surfaced as ``Event loop is closed`` and
# ``attached to a different loop`` from a second event loop, minutes of
# debugging away from the actual cause.
# ``tests/unit/core/test_redis_single_accessor.py`` now fails the build instead.
_redis: Redis | None = None

#: The client built for the loop in ``_client_loop``. Replaced, never reused, the
#: first time :func:`get_redis` is called on a different running loop.
_client: Redis | None = None
_client_loop: asyncio.AbstractEventLoop | None = None


def get_redis() -> Redis:
    """Return the async Redis client for the event loop that is running now.

    The single accessor, and therefore the single seam: a test that replaces
    ``src.core.redis._redis`` redirects every Redis-backed control in the
    process, on every loop, because they all resolve the client through this
    call rather than holding one from import time.

    Otherwise each running loop gets a client of its own, built on first use and
    kept for the rest of that loop — see the comment above ``_redis`` for why a
    client may never serve two loops. Called with no loop running (a sync
    dependency in the API's thread pool), it returns the current loop's client,
    which in a one-loop process is the only one there is.
    """
    global _client, _client_loop
    if _redis is not None:
        return _redis
    try:
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _client is None or (loop is not None and _client_loop not in (None, loop)):
        _client = Redis.from_url(settings.redis_url, decode_responses=True)
        _client_loop = loop
    elif _client_loop is None:
        _client_loop = loop
    return _client


async def close_redis() -> None:
    """Close the shared client's connection pool on application shutdown."""
    await get_redis().aclose()


async def drain_redis_pool() -> None:
    """Disconnect every connection the ending task's client pooled.

    ``redis.asyncio`` binds each
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
    ``RuntimeError`` — so "Refresh all SKUs" kept succeeding with
    ``funnel_rows: 0``. See :func:`src.core.tasks.run_task`, which drains this
    pool alongside the engine at every task boundary.

    Since 2026-09-28 the next task is handed a client of its own anyway (see
    :func:`get_redis`), so for the app's client this is what closes the sockets
    before their loop goes away rather than what keeps the next task alive. It
    still matters for a client swapped in through ``_redis``, which serves every
    loop — and it drains rather than closes so that such a client stays usable.
    """
    await get_redis().connection_pool.disconnect()


def _revocation_key(user_id: uuid.UUID) -> str:
    """Build the per-user revocation-watermark key."""
    return f"auth:revoked-after:{user_id}"


def _family_revocation_key(family_id: uuid.UUID) -> str:
    """Build the per-family revocation-watermark key."""
    return f"auth:family-revoked-after:{family_id}"


def _watermark_ttl() -> int:
    """How long a watermark must outlive the tokens it invalidates.

    Exactly the access-token lifetime plus a clock-skew margin: past that every
    token it could refuse has expired on its own, so keeping the key would only
    hold memory.
    """
    return settings.access_token_ttl_seconds + 60


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
    ttl = _watermark_ttl()
    try:
        await get_redis().set(key, str(datetime.now(UTC).timestamp()), ex=ttl)
    except RedisError as exc:
        # The lossy direction: this revocation is not merely delayed, it is
        # gone. Whoever asked for it believes it happened.
        report_degraded(
            CONTROL_SESSION_REVOCATION,
            detail=f"watermark write lost for user {user_id}: {type(exc).__name__}: {exc}",
        )
        return
    report_healthy(CONTROL_SESSION_REVOCATION)


async def sessions_revoked_after(user_id: uuid.UUID) -> datetime | None:
    """Return the user's revocation watermark, or ``None`` when unset.

    Args:
        user_id: The authenticated principal being checked.

    Returns:
        The UTC instant before which all issued tokens are invalid, or ``None``
        when no revocation is in force (or Redis is unreachable — fail open).
    """
    try:
        raw = await get_redis().get(_revocation_key(user_id))
    except RedisError as exc:
        report_degraded(
            CONTROL_SESSION_REVOCATION,
            detail=f"revocation check skipped: {type(exc).__name__}: {exc}",
        )
        return None
    report_healthy(CONTROL_SESSION_REVOCATION)
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError):
        logger.error("Corrupt revocation watermark for user %s: %r", user_id, raw)
        return None


async def mark_family_revoked(family_id: uuid.UUID) -> None:
    """End one login lineage's access tokens, and only that lineage's.

    The narrow counterpart to :func:`mark_user_sessions_revoked`. Called when a
    single family is revoked — a logout, or a detected refresh-token replay —
    so the access tokens already handed out on that lineage stop working now
    instead of surviving up to their full TTL.

    **Stamp this, never the per-user key, for a family-scoped act.** That
    distinction is not stylistic: revoking account-wide on a replay is what
    turned one woken-up laptop into a team-wide sign-out on 2026-07-27, and the
    same mistake made through this door would look like a logout button that
    signs out your colleagues.

    Callers must revoke the refresh rows *first* and stamp second, matching
    :meth:`AuthService.revoke_all_sessions`: the reverse order leaves a gap in
    which a rotation racing the call mints a pair whose ``iat`` is past the
    watermark and therefore survives it.

    Args:
        family_id: The login lineage to end.
    """
    try:
        await get_redis().set(
            _family_revocation_key(family_id),
            str(datetime.now(UTC).timestamp()),
            ex=_watermark_ttl(),
        )
    except RedisError as exc:
        report_degraded(
            CONTROL_SESSION_REVOCATION,
            detail=f"family watermark write lost for {family_id}: {type(exc).__name__}: {exc}",
        )
        return
    report_healthy(CONTROL_SESSION_REVOCATION)


async def family_revoked_after(family_id: uuid.UUID) -> datetime | None:
    """Return the lineage's revocation watermark, or ``None`` when unset.

    Args:
        family_id: The login lineage carried by the presented access token.

    Returns:
        The UTC instant before which tokens of this lineage are invalid, or
        ``None`` when none is in force (or Redis is unreachable — fail open,
        for the same reason :func:`sessions_revoked_after` does).
    """
    try:
        raw = await get_redis().get(_family_revocation_key(family_id))
    except RedisError as exc:
        report_degraded(
            CONTROL_SESSION_REVOCATION,
            detail=f"family revocation check skipped: {type(exc).__name__}: {exc}",
        )
        return None
    report_healthy(CONTROL_SESSION_REVOCATION)
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (TypeError, ValueError):
        logger.error("Corrupt family revocation watermark for %s: %r", family_id, raw)
        return None
