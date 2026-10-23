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
from collections.abc import Collection, Iterable

from redis.exceptions import RedisError

from src.core.celery_app import celery_app
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.modules.workspaces.backfill import LANE_ORDER, start_backfill
from src.modules.workspaces.models import BackfillLane, TokenKind

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
#: advertising lanes itself once the cards are registered, so when it runs
#: those two are not enqueued here as well.
CATALOGUE_BACKFILL_TASK_NAME = "monitoring.backfill_catalogue"

#: The funnel and advertising lanes, enqueued directly only when the catalogue
#: lane is NOT re-run — an analytics or promotion token added to a workspace
#: whose catalogue is already registered.
FUNNEL_BACKFILL_TASK_NAME = "monitoring.backfill_funnel"
ADVERTISING_BACKFILL_TASK_NAME = "monitoring.backfill_advertising"

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

#: The token kinds the first-run harvests read. Discovery reads content,
#: analytics, promotion, prices and statistics; the finance walk reads finance
#: (and content and analytics for its internal extras). A surface outside this
#: set — "Questions and reviews", "Chat", "Supplies" and the rest — unlocks nothing
#: either harvest or any backfill lane could use.
#:
#: Observed on 2026-10-02: a `feedback` token added to a workspace
#: whose history had loaded weeks earlier, reset all four lanes to "Queued…"
#: and re-walked the whole history — the shared WB budget and the worker's
#: 768 MiB spent on rows already held.
HARVEST_SURFACES: frozenset[TokenKind] = frozenset(
    {
        TokenKind.CONTENT,
        TokenKind.ANALYTICS,
        TokenKind.PROMOTION,
        TokenKind.PRICES,
        TokenKind.STATISTICS,
        TokenKind.FINANCE,
    }
)

#: Which backfill lanes a newly reachable surface is worth re-walking.
#:
#: A lane that ran without its token finished at once with "no token", so
#: the token arriving later is exactly when that lane has to run again — and
#: only that lane: the others already hold their history. Content brings the
#: funnel and advertising lanes with it because the catalogue lane starts both
#: itself once the cards are registered.
LANES_BY_SURFACE: dict[TokenKind, tuple[BackfillLane, ...]] = {
    TokenKind.CONTENT: (BackfillLane.CATALOGUE, BackfillLane.FUNNEL, BackfillLane.ADVERTISING),
    TokenKind.ANALYTICS: (BackfillLane.FUNNEL,),
    TokenKind.PROMOTION: (BackfillLane.ADVERTISING,),
    TokenKind.FINANCE: (BackfillLane.PNL,),
}

#: How long one bootstrap claim stands. A primary workspace holds thirteen
#: token kinds, and an owner pasting them one at a time saves the form
#: repeatedly — each save legitimately adding a kind that was not there before.
#: Without a debounce that is thirteen full catalogue harvests racing each other
#: for WB's shared rate budget to write the same rows. Fifteen minutes is longer
#: than the task's own 10-minute ceiling, so the claim cannot expire while the
#: harvest it represents is still running.
#:
#: Claimed per harvest and per lane rather than once per workspace: an owner
#: who pastes "Analytics" and then "Finance" five minutes later must still get
#: the P&L lane the second save unlocked.
_CLAIM_TTL_SECONDS = 15 * 60


def newly_reachable(before: Iterable[str], after: Iterable[str]) -> frozenset[TokenKind]:
    """The harvest surfaces a token save made reachable that were not before.

    Resolved the way the token bundle resolves them: ``unified`` stands in for
    every surface, so a category token added beside an existing ``unified``
    reaches nothing new, and ``unified`` added beside category tokens reaches
    only what they did not already cover.

    Args:
        before: Token-kind slugs configured before the save.
        after: Token-kind slugs configured after it.

    Returns:
        The surfaces worth a bootstrap; empty when the save unlocked nothing
        the harvests or the backfill read.
    """

    def _reach(configured: Iterable[str]) -> frozenset[TokenKind]:
        kinds = set(configured)
        if TokenKind.UNIFIED in kinds:
            return HARVEST_SURFACES
        return frozenset(kind for kind in HARVEST_SURFACES if kind in kinds)

    return _reach(after) - _reach(before)


#: Every bootstrap claim — the workspace's own and each lane's — starts with this.
_CLAIM_PREFIX = "workspaces:token-bootstrap:"


async def bootstrap_in_flight() -> bool:
    """Whether any workspace's first-run harvests may be running right now.

    For optional walks to step aside: a claim stands for the whole window in
    which discovery and the first finance harvest can hold the worker's memory
    (see :data:`FINANCE_TASK_NAME` on what overlapping them cost). Advisory, and
    open on failure — a Redis that cannot answer reports nothing in flight,
    because the scheduled work is still owed and the broker is that same Redis.

    Returns:
        ``True`` when at least one bootstrap claim is held.
    """
    try:
        async for _ in get_redis().scan_iter(match=f"{_CLAIM_PREFIX}*", count=500):
            return True
    except RedisError:
        logger.warning("Could not read bootstrap claims; assuming none is in flight.")
    return False


def _claim_key(workspace_id: uuid.UUID, lane: BackfillLane | None = None) -> str:
    """Build the debounce key for one workspace's harvests, or for one lane."""
    key = f"{_CLAIM_PREFIX}{workspace_id}"
    return key if lane is None else f"{key}:{lane}"


async def _claim(key: str) -> bool:
    """Take a debounce claim; ``False`` when someone already holds it."""
    return bool(await get_redis().set(key, b"1", ex=_CLAIM_TTL_SECONDS, nx=True))


def _lane_tasks(lanes: Collection[BackfillLane]) -> list[str]:
    """The tasks that start ``lanes`` — never a lane that was not asked for.

    The catalogue lane starts funnel and advertising itself, so with it in the
    set those two are not sent a second time.
    """
    names: list[str] = []
    if BackfillLane.CATALOGUE in lanes:
        names.append(CATALOGUE_BACKFILL_TASK_NAME)
    else:
        if BackfillLane.FUNNEL in lanes:
            names.append(FUNNEL_BACKFILL_TASK_NAME)
        if BackfillLane.ADVERTISING in lanes:
            names.append(ADVERTISING_BACKFILL_TASK_NAME)
    if BackfillLane.PNL in lanes:
        names.append(PNL_BACKFILL_TASK_NAME)
    return names


async def enqueue_catalogue_bootstrap(
    workspace_id: uuid.UUID, surfaces: Collection[TokenKind]
) -> str | None:
    """Enqueue the first harvests, and the backfill lanes, new credentials unlock.

    Scoped to ``surfaces``: a surface no harvest reads enqueues nothing, and
    only the lanes a new surface feeds are reset and walked (see
    :data:`LANES_BY_SURFACE`). Debounced per workspace for the harvests and per
    lane for the backfill: the first caller within the TTL claims the run and
    every other one is told it is already covered, so a burst of saves costs
    one harvest. Redis is the claim store rather than an in-process flag
    because the API runs as more than one container, and two of them saving
    tokens for the same workspace must still produce one task.

    Args:
        workspace_id: The workspace whose credentials just changed. Its caller
            must already have proved the workspace belongs to their
            organisation — this function performs no tenancy check of its own
            and would happily harvest any id it is handed.
        surfaces: The surfaces the save made reachable
            (:func:`newly_reachable`).

    Returns:
        The DISCOVERY task's id when it was enqueued, or ``None`` when it was
        not — the surfaces unlock nothing, a recent bootstrap already covers
        this workspace, or the broker could not be reached. All are ordinary
        outcomes, not failures: the scheduled harvests remain the backstop.
        The id is returned for logging and tests; the caller does not wait on
        it, and the finance walk's id is deliberately not plumbed out, because
        nothing polls it.
    """
    relevant = frozenset(surfaces) & HARVEST_SURFACES
    if not relevant:
        logger.info(
            "New WB credentials for workspace %s reach nothing the harvests read; "
            "not enqueueing a bootstrap.",
            workspace_id,
        )
        return None
    wanted = {lane for surface in relevant for lane in LANES_BY_SURFACE.get(surface, ())}
    try:
        harvest = await _claim(_claim_key(workspace_id))
        lanes = tuple(
            [
                lane
                for lane in LANE_ORDER
                if lane in wanted and await _claim(_claim_key(workspace_id, lane))
            ]
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
    if not harvest and not lanes:
        logger.info(
            "A token-triggered harvest for workspace %s is already claimed; not enqueueing "
            "a second one.",
            workspace_id,
        )
        return None

    kwargs = {"workspace_id": str(workspace_id)}
    # Seeded BEFORE anything is enqueued, so the profile has its lanes to draw
    # the moment the seller finishes signing up. A panel that appears only once
    # the first tick has run is indistinguishable, for the minute it is absent,
    # from nothing having started at all. Only the lanes about to run: the rest
    # keep the progress they already have.
    if lanes:
        await start_backfill(workspace_id, lanes=lanes)
    try:
        result = None
        if harvest:
            # The finance walk is attached as a callback, not sent now: `link`
            # fires it when discovery finishes, so the two never hold memory at
            # the same time. `immutable=True` because discovery returns its row
            # counts and a mutable signature would prepend them to the finance
            # task's arguments.
            #
            # `link_error` carries the same signature, so a discovery that FAILS
            # still leaves the seller with a P&L. The two are mutually exclusive
            # — Celery fires one or the other — so this cannot double-enqueue.
            finance = celery_app.signature(FINANCE_TASK_NAME, kwargs=kwargs, immutable=True)
            result = celery_app.send_task(
                DISCOVERY_TASK_NAME, kwargs=kwargs, link=finance, link_error=finance
            )
        # The history walks go on the END of the same chain, never beside it.
        # Each is a tick that does one bounded step and re-enqueues itself, so
        # they cost a worker slot for ~90 s at a time rather than holding one
        # for hours — but the FIRST step of each would still land in the same
        # second as the two harvests above if it were sent now, which is the
        # arrangement the OOM note on FINANCE_TASK_NAME records.
        lane_tasks = _lane_tasks(lanes)
        for task_name in lane_tasks:
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
        "New WB credentials (%s) for workspace %s; harvest task %s, history backfill %s "
        "queued %d s out.",
        ", ".join(sorted(relevant)),
        workspace_id,
        None if result is None else result.id,
        lane_tasks,
        _BACKFILL_DELAY_SECONDS,
    )
    return None if result is None else str(result.id)
