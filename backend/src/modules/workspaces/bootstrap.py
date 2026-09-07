"""Kicking off a first harvest the moment a workspace's WB credentials appear.

A seller who has just pasted a token has an empty workspace, and until this
module existed nothing connected the two events: the credential was stored, and
the data it unlocks arrived at 06:00 MSK the next morning with the nightly
``monitoring.harvest_all``. Nothing in between reported an error, so the only
signal the seller got was a product page with no products on it.

**Why the task is named rather than imported.** ``workspaces.contract`` imports
``workspaces.services``, and ``monitoring.contract`` imports
``monitoring.services``, which imports ``workspaces.contract`` — so a direct
``from src.modules.monitoring.contract import ...`` here closes an import
cycle. Addressing the task by its registered name through Celery keeps the two
modules unaware of each other (``src.core`` is shared ground, not a module), at
the cost of a string that no type checker can follow. That cost is paid back in
``tests/unit/workspaces/test_token_bootstrap.py``, which asserts the name is
actually registered — a rename that skipped this file fails there rather than
in production, where the symptom would be a silent no-op.

**Nothing here may raise.** Storing a WB token is the caller's real request;
enqueueing a harvest is a courtesy attached to it. A broker that has gone away
must cost the seller a slower first harvest, not a failed save and the belief
that their token did not stick.
"""

from __future__ import annotations

import uuid

from redis.exceptions import RedisError

from src.core.celery_app import celery_app
from src.core.logging import get_logger
from src.core.redis import get_redis

logger = get_logger(__name__)

#: The registered name of the single-workspace discovery task
#: (``src.modules.monitoring.tasks.discovery``). See the module docstring for
#: why this is a string and what guards it.
DISCOVERY_TASK_NAME = "monitoring.discover_workspace"

#: How long one workspace's bootstrap claim stands. A primary workspace holds
#: thirteen token kinds, and an owner pasting them one at a time saves the form
#: repeatedly — each save legitimately adding a kind that was not there before.
#: Without a debounce that is thirteen full catalogue harvests racing each other
#: for WB's shared rate budget to write the same rows. Fifteen minutes is longer
#: than the task's own 10-minute ceiling, so the claim cannot expire while the
#: harvest it represents is still running.
_CLAIM_TTL_SECONDS = 15 * 60


def _claim_key(workspace_id: uuid.UUID) -> str:
    """Build the debounce key for one workspace's token-triggered bootstrap."""
    return f"workspaces:token-bootstrap:{workspace_id}"


async def enqueue_catalogue_bootstrap(workspace_id: uuid.UUID) -> str | None:
    """Enqueue a discovery harvest for a workspace that just gained a token.

    Debounced per workspace: the first caller within the TTL claims the run and
    every other one is told it is already covered, so a burst of saves costs one
    harvest. Redis is the claim store rather than an in-process flag because the
    API runs as more than one container, and two of them saving tokens for the
    same workspace must still produce one task.

    Args:
        workspace_id: The workspace whose credentials just changed. Its caller
            must already have proved the workspace belongs to their
            organisation — this function performs no tenancy check of its own
            and would happily harvest any id it is handed.

    Returns:
        The enqueued task's id, or ``None`` when nothing was enqueued — either
        a recent bootstrap already covers this workspace, or the broker could
        not be reached. Both are ordinary outcomes, not failures: the nightly
        harvest remains the backstop in either case.
    """
    try:
        claimed = await get_redis().set(
            _claim_key(workspace_id), b"1", ex=_CLAIM_TTL_SECONDS, nx=True
        )
    except RedisError:
        # Celery's broker is this same Redis, so a failure here means the
        # enqueue below cannot succeed either. Skipping is honest; trying
        # anyway would only turn one logged warning into two.
        logger.exception(
            "Redis unavailable: skipping the token-triggered harvest for workspace %s; "
            "the nightly harvest will pick it up.",
            workspace_id,
        )
        return None
    if not claimed:
        logger.info(
            "A token-triggered harvest for workspace %s is already claimed; not enqueueing "
            "a second one.",
            workspace_id,
        )
        return None

    try:
        result = celery_app.send_task(
            DISCOVERY_TASK_NAME, kwargs={"workspace_id": str(workspace_id)}
        )
    except Exception:
        # Broad on purpose. Every exception Celery's transport can raise on
        # enqueue is one the seller must not see: their token IS saved, and
        # this call is the courtesy attached to it.
        logger.exception(
            "Could not enqueue the token-triggered harvest for workspace %s; "
            "the nightly harvest will pick it up.",
            workspace_id,
        )
        return None
    logger.info(
        "New WB credentials for workspace %s; enqueued discovery task %s.",
        workspace_id,
        result.id,
    )
    return str(result.id)
