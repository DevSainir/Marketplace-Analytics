"""Ownership binding for interactive «Обновить» refresh tasks.

``POST /skus/{nm_id}/refresh`` returns a Celery task id, and
``GET /refresh/{task_id}`` reports its state. Celery's ``AsyncResult`` knows
nothing about tenancy, so without this binding any authenticated caller could
poll any task id in the broker and learn whether some other workspace's harvest
had run and whether it succeeded. Small as that leak is, it was the one endpoint
in the module with no workspace check at all.

So the enqueue records ``task id -> workspace`` and the poll refuses ids it
cannot attribute to the caller's workspace, answering exactly as it would for
an id that never existed.

The binding lives in Redis rather than PostgreSQL because it is bounded,
disposable state with the same lifetime as the Celery result it describes — it
is not a fact about the business. Availability policy matches
:mod:`src.core.redis`: a Redis outage makes the poll report "unknown task",
which the frontend already handles by stopping the poll, rather than blocking
the refresh feature outright.
"""

from __future__ import annotations

import uuid

from redis.exceptions import RedisError

from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)

#: How long a task id stays attributable. Comfortably longer than both the
#: harvest itself and the frontend's ~2-minute poll ceiling, and shorter than
#: Celery's own ``result_expires`` (1 h) so a binding never outlives the result
#: it points at.
_BINDING_TTL_SECONDS = 15 * 60


def _binding_key(task_id: str) -> str:
    """Build the per-task ownership key."""
    return f"monitoring:refresh-task:{task_id}"


async def bind_task_to_workspace(task_id: str, workspace_id: uuid.UUID) -> None:
    """Record which workspace enqueued a refresh task.

    Args:
        task_id: The Celery task id handed back to the client.
        workspace_id: The workspace whose SKU is being refreshed.
    """
    try:
        await get_redis().set(_binding_key(task_id), str(workspace_id), ex=_BINDING_TTL_SECONDS)
    except RedisError:
        logger.exception(
            "Redis unavailable: could not record ownership of refresh task %s; "
            "its status endpoint will report the task as unknown.",
            task_id,
        )


async def task_belongs_to_workspace(task_id: str, workspace_id: uuid.UUID) -> bool:
    """Return whether a task id was enqueued by the given workspace.

    Args:
        task_id: The Celery task id presented by the client.
        workspace_id: The caller's active workspace.

    Returns:
        ``True`` only when a binding exists AND names this workspace. An
        unknown id, an expired binding, and another tenant's id are all
        indistinguishable ``False`` — the caller learns nothing either way.
    """
    try:
        raw = await get_redis().get(_binding_key(task_id))
    except RedisError:
        logger.exception("Redis unavailable: cannot verify ownership of refresh task %s.", task_id)
        return False
    if raw is None:
        return False
    # The shared client sets decode_responses=True, so this is a str at runtime —
    # but redis-py types `get` as `bytes | str | None` because that flag is a
    # constructor argument the type system cannot see. Decoding explicitly keeps
    # the comparison correct whichever the stub says.
    owner = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return owner == str(workspace_id)
