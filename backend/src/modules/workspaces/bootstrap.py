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
from src.modules.workspaces.backfill import start_backfill

logger = get_logger(__name__)

#: The registered name of the single-workspace discovery task
#: (``src.modules.monitoring.tasks.discovery``). See the module docstring for
#: why this is a string and what guards it.
DISCOVERY_TASK_NAME = "monitoring.discover_workspace"

#: The registered name of the per-workspace finance walk
#: (``src.modules.finreports.tasks``). Chained BEHIND discovery rather than
#: enqueued alongside it.
#:
#: They were enqueued together on the reasoning that they read different WB
#: surfaces and therefore do not contend. They contend for something else: the
#: worker's 768 MB cgroup, whose ceiling was measured for one harvest at a time
#: (see the `mem_limit` note in docker-compose.yml). On 2026-09-07 the first
#: outside signup's two first-run harvests overlapped and the kernel OOM-killed
#: the finance child 15 s in — `WorkerLostError: signal 9`, no retry, and a
#: workspace left with a full catalogue and an empty P&L. Nothing else in the
#: schedule overlaps: the hourly finance tick already skips 05:00-07:00 MSK so
#: it cannot meet the nightly monitoring harvest. This was the one place two
#: heavy walks were started in the same second, and it is now a queue of two.
FINANCE_TASK_NAME = "finreports.harvest_finance"

#: The catalogue lane of the history backfill. It starts the funnel and
#: advertising lanes itself once the cards are registered, so only two names
#: are enqueued here rather than four.
CATALOGUE_BACKFILL_TASK_NAME = "monitoring.backfill_catalogue"

#: The P&L lane. Sent alongside the catalogue rather than behind it: it does
#: not need the SKU list (settlement rows carry their own ``nm_id``), and at
#: one WB request a minute per method it is still the lane whose first page
#: matters most — it was one per fifteen minutes until 2026-09-22.
PNL_BACKFILL_TASK_NAME = "finreports.backfill_pnl"

#: How long the backfill waits before its first step. Long enough for the two
#: first-run harvests chained above to finish and release their memory — the
#: whole reason those two are a queue rather than a pair (see
#: :data:`FINANCE_TASK_NAME`). The backfill has hours; it can afford ten
#: minutes of politeness.
_BACKFILL_DELAY_SECONDS = 10 * 60

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
    """Enqueue the first monitoring and finance harvests for new credentials.

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
        The DISCOVERY task's id when anything was enqueued, or ``None`` when
        nothing was — either a recent bootstrap already covers this workspace,
        or the broker could not be reached. Both are ordinary outcomes, not
        failures: the scheduled harvests remain the backstop in either case.
        The id is returned for logging and tests; the caller does not wait on
        it, and the finance walk's id is deliberately not plumbed out, because
        nothing polls it.
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

    kwargs = {"workspace_id": str(workspace_id)}
    # Seeded BEFORE anything is enqueued, so the profile has four lanes to draw
    # the moment the seller finishes signing up. A panel that appears only once
    # the first tick has run is indistinguishable, for the minute it is absent,
    # from nothing having started at all.
    await start_backfill(workspace_id)
    # The finance walk is attached as a callback, not sent now: `link` fires it
    # when discovery finishes, so the two never hold memory at the same time.
    # `immutable=True` because discovery returns its row counts and a mutable
    # signature would prepend them to the finance task's arguments.
    #
    # `link_error` carries the same signature, so a discovery that FAILS still
    # leaves the seller with a P&L. The two are mutually exclusive — Celery
    # fires one or the other — so this cannot double-enqueue the walk.
    finance = celery_app.signature(FINANCE_TASK_NAME, kwargs=kwargs, immutable=True)
    try:
        result = celery_app.send_task(
            DISCOVERY_TASK_NAME, kwargs=kwargs, link=finance, link_error=finance
        )
        # The history walks go on the END of the same chain, never beside it.
        # Each is a tick that does one bounded step and re-enqueues itself, so
        # they cost a worker slot for ~90 s at a time rather than holding one
        # for hours — but the FIRST step of each would still land in the same
        # second as the two harvests above if it were sent now, which is the
        # arrangement the OOM note on FINANCE_TASK_NAME records.
        for task_name in (CATALOGUE_BACKFILL_TASK_NAME, PNL_BACKFILL_TASK_NAME):
            celery_app.send_task(task_name, kwargs=kwargs, countdown=_BACKFILL_DELAY_SECONDS)
    except Exception:
        # Broad on purpose: every exception Celery's transport can raise on
        # enqueue is one the seller must not see — their token IS saved, and
        # this call is the courtesy attached to it.
        logger.exception(
            "Could not enqueue %s for workspace %s; its scheduled run will pick it up.",
            DISCOVERY_TASK_NAME,
            workspace_id,
        )
        return None
    logger.info(
        "New WB credentials for workspace %s; enqueued %s as task %s, with %s chained behind "
        "it and the history backfill (%s, %s) queued %d s out.",
        workspace_id,
        DISCOVERY_TASK_NAME,
        result.id,
        FINANCE_TASK_NAME,
        CATALOGUE_BACKFILL_TASK_NAME,
        PNL_BACKFILL_TASK_NAME,
        _BACKFILL_DELAY_SECONDS,
    )
    return str(result.id)
