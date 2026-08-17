"""The one place a search-position sample is stored and read.

A probe is not a fact to keep: the ranking is computed per delivery region and
loyalty tier and moves within the hour, so nothing here reaches Postgres. What it
needs instead is a short-lived, SHARED place, because two very different callers
must agree about the same phrase:

* the read endpoint behind «Позиция в выдаче», which only ever reads;
* the Celery task behind «Проверить позицию», which does the slow, retried,
  frequently-refused work of getting an answer out of WB and writes it here.

That split is why this module exists rather than the cache living inside the
service: a finished task must make the ordinary cached read succeed, with no
second store to keep in step and no way for the two to disagree.

Keyed by phrase and REGION only — deliberately not by SKU. The probe reads whole
result pages, so one scan answers for every SKU in the workspace, and a colleague
checking the same phrase from another SKU's page reuses it instead of spending
WB's rate budget again.

Redis is optional (see :mod:`src.core.redis`): an outage costs a slower, more
throttled probe, never the feature.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from src.core.logging import get_logger
from src.core.redis import get_redis
from src.integrations.wildberries.clients.search import SearchProbe

logger = get_logger(__name__)


def probe_cache_key(*, query: str, dest: int) -> str:
    """Build the per-phrase, per-region cache key.

    Args:
        query: The phrase, as the seller typed it.
        dest: The delivery region the ranking was computed for. Part of the key
            because a position is only meaningful together with it.

    Returns:
        The Redis key.
    """
    return f"monitoring:search-position:{dest}:{query.casefold()}"


def serialize_probe(probe: SearchProbe, *, checked_at: datetime | None = None) -> dict[str, Any]:
    """Flatten a probe into the JSON shape the cache stores.

    Args:
        probe: The scan to store.
        checked_at: When WB answered. Defaults to now; the task passes its own so
            the pin row and the cached copy carry the SAME timestamp.

    Returns:
        A JSON-serialisable dict.
    """
    return {
        "normalized_query": probe.normalized_query,
        "total_found": probe.total_found,
        "positions_scanned": probe.positions_scanned,
        "truncated": probe.truncated,
        "checked_at": (checked_at or datetime.now(UTC)).isoformat(),
        "positions": [
            {
                "nm_id": position.nm_id,
                "position": position.position,
                "page": position.page,
                "position_on_page": position.position_on_page,
            }
            for position in probe.positions
        ],
    }


async def read_probe_result(query: str, *, dest: int, ttl_seconds: int) -> dict[str, Any] | None:
    """Return the stored scan for a phrase, or ``None`` when there is none.

    Args:
        query: The phrase to look up.
        dest: The delivery region whose ranking is wanted.
        ttl_seconds: The configured lifetime; ``0`` disables the cache entirely,
            which is how the unit tier keeps Redis out of arithmetic tests.

    Returns:
        The stored payload, or ``None`` if absent, expired, or unreadable.
    """
    if not ttl_seconds:
        return None
    key = probe_cache_key(query=query, dest=dest)
    try:
        raw = await get_redis().get(key)
    except RedisError:
        logger.warning("Redis unavailable: no cached position for %r.", query)
        return None
    if raw is None:
        return None
    payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        cached = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return cached if isinstance(cached, dict) else None


async def store_probe_result(
    *,
    query: str,
    probe: SearchProbe,
    dest: int,
    ttl_seconds: int,
    checked_at: datetime | None = None,
) -> None:
    """Store a fresh scan where the read endpoint will find it.

    Args:
        query: The phrase that was checked.
        probe: The scan WB answered with.
        dest: The delivery region it was computed for — part of the key.
        ttl_seconds: How long the sample stays useful; ``0`` disables storing.
        checked_at: When it answered (see :func:`serialize_probe`).
    """
    if not ttl_seconds:
        return
    key = probe_cache_key(query=query, dest=dest)
    try:
        await get_redis().set(
            key,
            json.dumps(serialize_probe(probe, checked_at=checked_at)),
            ex=ttl_seconds,
        )
    except RedisError:
        logger.warning("Redis unavailable: the probe for %r was not cached.", query)


#: How long a run marker outlives its task. Long enough that a seller who closed
#: the page mid-check still finds the check on return, short enough that a worker
#: killed mid-run cannot advertise a phantom forever.
RUN_MARKER_TTL_SECONDS = 15 * 60


def _run_key(*, workspace_id: str, nm_id: int) -> str:
    """Key of the in-flight check marker for one SKU's panel."""
    return f"monitoring:position-run:{workspace_id}:{nm_id}"


async def remember_run(*, workspace_id: str, nm_id: int, task_id: str, query: str) -> None:
    """Record that a check is in flight, so the panel can re-attach to it.

    The task id lives server-side rather than in the tab that started it: a check
    survives a reload, a navigation and a closed laptop, and the seller coming
    back has to SEE that it is still running. Without this the panel showed
    nothing on return and the work looked lost when it was merely elsewhere.

    Args:
        workspace_id: Owning workspace, so one tenant cannot observe another's.
        nm_id: The SKU whose panel started the check.
        task_id: The Celery id to poll.
        query: The phrase being checked, for the "проверяем «…»" line.
    """
    try:
        await get_redis().set(
            _run_key(workspace_id=workspace_id, nm_id=nm_id),
            json.dumps({"task_id": task_id, "query": query}),
            ex=RUN_MARKER_TTL_SECONDS,
        )
    except RedisError:
        logger.warning("Redis unavailable: the position check for %r is not resumable.", query)


async def current_run(*, workspace_id: str, nm_id: int) -> dict[str, Any] | None:
    """The check this SKU's panel last started, or ``None``.

    Args:
        workspace_id: Owning workspace.
        nm_id: The SKU whose panel is asking.

    Returns:
        ``{"task_id": ..., "query": ...}``, or ``None`` when nothing is in flight.
    """
    try:
        raw = await get_redis().get(_run_key(workspace_id=workspace_id, nm_id=nm_id))
    except RedisError:
        logger.warning("Redis unavailable: cannot report an in-flight position check.")
        return None
    if raw is None:
        return None
    payload = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        marker = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return marker if isinstance(marker, dict) else None


async def forget_run(*, workspace_id: str, nm_id: int) -> None:
    """Drop the marker once its result has been collected."""
    try:
        await get_redis().delete(_run_key(workspace_id=workspace_id, nm_id=nm_id))
    except RedisError:
        logger.warning("Redis unavailable: a finished position check stays marked in flight.")
