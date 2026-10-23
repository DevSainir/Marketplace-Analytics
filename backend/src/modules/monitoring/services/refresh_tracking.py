"""Ownership binding for interactive "Refresh" tasks.

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

import hashlib
import uuid
from collections.abc import Sequence

from redis.exceptions import RedisError

from src.core.config import settings
from src.core.exceptions import RateLimitError
from src.core.logging import get_logger
from src.core.ratelimit import consume_budget
from src.core.redis import get_redis

logger = get_logger(__name__)

#: How long a task id stays attributable. Must outlive the harvest it names:
#: a refresh now includes the sale feed and the 22-day buyout-cohort pass, whose
#: paced requests take ~7 minutes on their own, so the task's own ceiling is 25
#: minutes. At the previous 15 the binding could expire mid-run and the poll
#: would answer "unknown task" for a harvest that was still working — the same
#: visible failure as the 2026-07-30 poll-ceiling bug, from the other end.
#: Still under Celery's ``result_expires`` (1 h), so a binding never outlives
#: the result it points at.
_BINDING_TTL_SECONDS = 45 * 60


def _binding_key(task_id: str) -> str:
    """Build the per-task ownership key."""
    return f"monitoring:refresh-task:{task_id}"


def _inflight_key(workspace_id: uuid.UUID, nm_ids: Sequence[int]) -> str:
    """Build the key identifying "this workspace already asked for these SKUs".

    The SKU set is hashed rather than listed: a refresh-all in a large catalogue
    would otherwise build a key thousands of identifiers long. Sorting first
    makes the key depend on the *set*, so the same request in a different order
    is recognised as the same request.
    """
    digest = hashlib.sha256(",".join(str(nm) for nm in sorted(nm_ids)).encode()).hexdigest()
    return f"monitoring:refresh-inflight:{workspace_id}:{digest[:32]}"


async def spend_refresh_budget(workspace_id: uuid.UUID) -> None:
    """Charge one "Refresh" enqueue to the workspace's budget.

    The routes had no bound at all: every press enqueued another catalogue walk,
    so a held-down button (or a loop) could pile arbitrarily many onto a worker
    pool of four and starve every scheduled harvest behind them. The budget is
    per workspace because that is who spends the queue and the WB rate budget —
    keying it on the caller's address would let one tenant multiply its budget
    by its number of devices, and would make two colleagues behind one office NAT
    share a single one.

    Args:
        workspace_id: The workspace asking for a refresh.

    Raises:
        RateLimitError: When this workspace has spent its window's budget.
    """
    within_budget = await consume_budget(
        scope="monitoring-refresh-enqueue",
        subject=str(workspace_id),
        limit=settings.refresh_enqueue_attempts,
        window_seconds=settings.refresh_enqueue_window_seconds,
    )
    if not within_budget:
        raise RateLimitError("Too many refreshes in a row. Try again in a few minutes.")


async def task_already_running(workspace_id: uuid.UUID, nm_ids: Sequence[int]) -> str | None:
    """Return the id of an identical refresh still in flight, if there is one.

    Deduplication, not throttling: two presses of "Refresh" on the same card
    want one harvest and one task id to poll, not two runs racing to write the
    same rows. The budget above bounds abuse; this keeps ordinary impatience
    from costing anything at all.

    Args:
        workspace_id: The caller's active workspace.
        nm_ids: The SKUs the caller is asking to refresh.

    Returns:
        The task id to hand back instead of enqueuing, or ``None``.
    """
    try:
        raw = await get_redis().get(_inflight_key(workspace_id, nm_ids))
    except RedisError:
        logger.exception("Redis unavailable: cannot deduplicate the refresh; enqueueing.")
        return None
    if raw is None:
        return None
    return raw.decode("utf-8") if isinstance(raw, bytes) else raw


async def remember_running_task(
    workspace_id: uuid.UUID, nm_ids: Sequence[int], task_id: str
) -> None:
    """Record an enqueued refresh so an identical one reuses it.

    Args:
        workspace_id: The workspace that enqueued it.
        nm_ids: The SKUs it covers.
        task_id: The Celery task id to serve to a duplicate request.
    """
    try:
        await get_redis().set(
            _inflight_key(workspace_id, nm_ids),
            task_id,
            ex=settings.refresh_dedup_window_seconds,
        )
    except RedisError:
        logger.exception(
            "Redis unavailable: refresh task %s not recorded; a repeat press "
            "will enqueue a second run.",
            task_id,
        )


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


#: How long one workspace's buyout-cohort pass stays claimed. Cohorts mature
#: over ~3 weeks, so two passes minutes apart write identical rows — and each
#: costs 22 sequential rate-limited requests (~7 min). An hour is short enough
#: that a seller who waited out a WB outage can still force fresh cohorts, and
#: long enough that clicking "Refresh" on six SKUs in a row costs one pass
#: rather than six.
_COHORT_CLAIM_TTL_SECONDS = 60 * 60


def _cohort_claim_key(workspace_id: uuid.UUID) -> str:
    """Build the per-workspace cohort-pass claim key."""
    return f"monitoring:cohort-pass:{workspace_id}"


async def claim_cohort_pass(workspace_id: uuid.UUID) -> bool:
    """Claim the right to run this workspace's cohort pass, if it is free.

    The cohort surface is the most expensive thing a refresh touches and the
    least urgent: it re-reads order-date cohorts that keep maturing for about
    three weeks, so running it twice within the hour writes the same rows for
    the price of another 22 rate-limited requests. Refreshing several SKUs in
    a row is the ordinary case, and each of those refreshes would otherwise
    repeat the whole pass.

    Args:
        workspace_id: The workspace whose cohorts are about to be re-read.

    Returns:
        ``True`` when the caller should run the pass, ``False`` when a recent
        one already covers it. A Redis outage answers ``True`` — the pass is
        idempotent, so the failure that matters is skipping it, not repeating
        it.
    """
    try:
        claimed = await get_redis().set(
            _cohort_claim_key(workspace_id), "1", ex=_COHORT_CLAIM_TTL_SECONDS, nx=True
        )
    except RedisError:
        logger.exception(
            "Redis unavailable: cannot deduplicate the cohort pass for workspace %s; running it.",
            workspace_id,
        )
        return True
    return bool(claimed)
