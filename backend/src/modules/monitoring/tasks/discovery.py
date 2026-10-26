"""The nightly all-workspace harvest: discover SKUs, then harvest each workspace."""

from __future__ import annotations

import uuid
from datetime import timedelta

from celery import Task

# Sync on purpose: the lock outlives the event loop `run_task` builds and tears down.
from redis import Redis as SyncRedis  # noqa: TID251
from redis.exceptions import LockError

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.harvest import harvest_timer, record_harvest_outcome
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBContentClient
from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.repos import ProductCardRepository
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.monitoring.tasks.full_refresh import (
    ProgressReporter,
    celery_progress,
    refresh_workspace_data,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)

#: Metric label for the nightly whole-account pass. A constant for the same
#: reason as its siblings in `harvest.py` and `finreports/tasks/harvest.py`: a
#: label that differs by a character between the timer and the row counter
#: produces two unrelated series that each look half-broken.
HARVEST_NIGHTLY = "monitoring.nightly"

#: Distributed-lock name preventing overlapping full harvests (the WB
#: advertising surface allows ~1 req/min — two concurrent harvests starve
#: each other into retry exhaustion).
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"

#: Generous ceiling on one harvest run; the lock auto-expires after this so a
#: crashed worker can never wedge the nightly schedule permanently.
_HARVEST_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60


async def _discover_and_harvest_workspace(
    tokens: WorkspaceTokenBundle,
    days: int,
    *,
    include_cohorts: bool = True,
    progress: ProgressReporter | None = None,
) -> dict[str, int]:
    """Discover one workspace's SKUs and harvest a rolling ``days``-day window.

    Discovery runs with the workspace's own Content token — the Analytics one
    when no Content token is stored — against the Content API, so the resulting
    cards, and everything harvested for them, are provably that workspace's
    SKUs.

    Discovery is a SOURCE, not a precondition. When the Content API refuses
    (no token, or one whose categories do not include "Content"), the harvest
    falls back to the SKUs already registered to the workspace and runs every
    other source over them; only a workspace with no catalogue at all has
    nothing left to harvest. Letting it abort instead cost a
    workspace every nightly harvest from the day WB stopped serving
    ``/content/v2/get/cards/list`` on the analytics scope: funnel, advertising,
    stocks and prices all went unharvested because the SKU LIST could not be
    refreshed, though it had not changed.

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: Length of the inclusive window ending yesterday (Moscow time).
        include_cohorts: Whether to re-read the buyout cohorts in the same pass.
            The nightly fleet walk passes ``False`` because
            ``monitoring.refresh_buyout_cohorts`` owns that hour; the
            single-workspace entrypoint leaves it ``True``, because the person
            who triggered it is waiting for "Buyout rate" to move.

    Returns:
        A mapping of persisted row counts per metric family.

    Raises:
        IntegrationError: If discovery fails and the workspace has no SKUs on
            file, leaving nothing to harvest.
    """
    if settings.wb_fake_harvest:
        # Fake harvesting never calls the Content API. The SKUs already on file
        # keep their catalogue rows (vendor codes + size labels), so discovery
        # just re-harvests them with fresh synthetic facts — no card refresh
        # (``cards=None``), and no invented/garbage SKUs.
        async with AsyncSessionLocal() as session:
            nm_ids = await ProductCardRepository(session).list_workspace_nm_ids(tokens.workspace_id)
        cards: list[WBCard] | None = None
    else:
        try:
            if not tokens.content:
                raise IntegrationError(
                    f"Workspace '{tokens.name}' has no content/analytics token; "
                    "cannot discover its SKUs."
                )
            async with WBContentClient(settings, token=tokens.content) as content:
                fetched = await content.fetch_all_cards()
        except Exception as exc:
            # The catalogue is the one source whose failure used to void the
            # others. It is also the most static of them: yesterday's SKU list
            # is a fine basis for harvesting yesterday's facts, so fall back to
            # it rather than skip the workspace.
            async with AsyncSessionLocal() as session:
                nm_ids = await ProductCardRepository(session).list_workspace_nm_ids(
                    tokens.workspace_id
                )
            if not nm_ids:
                raise IntegrationError(
                    f"Workspace '{tokens.name}' has no SKUs on file and its catalogue "
                    f"could not be read: {exc}"
                ) from exc
            logger.warning(
                "Catalogue refresh failed for workspace '%s' (%s); harvesting the "
                "%d SKU(s) already on file instead.",
                tokens.name,
                exc,
                len(nm_ids),
            )
            cards = None
        else:
            nm_ids = [card.nm_id for card in fetched]
            cards = fetched
            logger.info(
                "Discovered %d SKUs for workspace '%s'.",
                len(nm_ids),
                tokens.name,
            )
    if not nm_ids:
        return {}

    # Every line from here on names the seller this run is working for. The
    # nightly pass walks every workspace inside one task, so the task-level
    # context names none of them.
    bind_workspace(tokens.workspace_id)

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    with harvest_timer(HARVEST_NIGHTLY):
        outcome = await refresh_workspace_data(
            tokens=tokens,
            nm_ids=nm_ids,
            date_from=start,
            date_to=end,
            cards=cards,
            include_cohorts=include_cohorts,
            progress=progress,
        )
    # The nightly run is the one the row counters exist FOR. It is this pass
    # that reported SUCCESS with `funnel_rows: 0` for days in the 2026-07-30
    # incident, and the `HarvestProducingNoRows` alert is written against
    # exactly this metric — so a nightly harvest that recorded nothing would
    # leave that alert unable to fire for the harvest it was designed around.
    record_harvest_outcome(
        HARVEST_NIGHTLY,
        counts=outcome.counts,
        failed_sources=outcome.failed_sources,
    )
    # A partial WB outage must be visible in the nightly run's own log line, not
    # only inferable from a suspiciously round zero in the counts.
    if outcome.failed_sources:
        logger.warning(
            "Workspace '%s' harvested with %d WB source(s) withheld: %s.",
            tokens.name,
            len(outcome.failed_sources),
            ", ".join(outcome.failed_sources),
        )
    return outcome.counts


async def _discover_and_harvest(days: int) -> dict[str, int]:
    """Harvest every workspace with stored WB tokens, sequentially.

    Sequential (not gathered) on purpose: WB rate-limits per seller account,
    but the process shares one event loop, DB pool, and card-proxy budget —
    and a failed workspace must not poison the others' harvests. Failures are
    logged per workspace and skipped; the run fails only when *every*
    workspace failed (so a single revoked token cannot mask a systemic
    outage into a "success").

    Args:
        days: Length of the inclusive window ending yesterday (Moscow time).

    Returns:
        A mapping of persisted row counts per metric family, summed across
        workspaces, plus ``workspaces_harvested`` / ``workspaces_failed``.

    Raises:
        IntegrationError: When workspaces exist but every one failed.
    """
    async with AsyncSessionLocal() as session:
        bundles = await load_workspace_token_bundles(session)
    if not bundles:
        logger.warning("No workspaces configured; nothing to harvest.")
        return {"workspaces_harvested": 0, "workspaces_failed": 0}

    totals: dict[str, int] = {"workspaces_harvested": 0, "workspaces_failed": 0}
    failures: list[str] = []
    for bundle in bundles:
        try:
            # No cohorts here: ``monitoring.refresh_buyout_cohorts`` sweeps
            # every workspace at 05:20 MSK, right after this pass. Running
            # them in both would spend 22 rate-limited requests per workspace
            # to write rows the 05:20 pass immediately rewrites.
            result = await _discover_and_harvest_workspace(bundle, days, include_cohorts=False)
        except Exception as exc:  # isolate workspaces from each other
            logger.warning("Harvest failed for workspace '%s': %s", bundle.name, exc)
            failures.append(bundle.name)
            totals["workspaces_failed"] += 1
            continue
        totals["workspaces_harvested"] += 1
        for key, value in result.items():
            totals[key] = totals.get(key, 0) + value

    if totals["workspaces_harvested"] == 0:
        # Count, not names: this message travels into the Celery result payload
        # and anywhere that is read from, and the names are every tenant on the
        # platform. Each failure is already logged individually above, with the
        # workspace it belongs to.
        raise IntegrationError(f"Every workspace harvest failed ({len(failures)}); see logs.")
    return totals


#: Ceiling on the discovery bootstrap — the same 25 minutes the interactive SKU
#: refresh gets, and for the same reason: the two now run the identical body
#: (:func:`~src.modules.monitoring.tasks.full_refresh.refresh_workspace_data`),
#: so a different ceiling would only mean one of them being killed at a point
#: the other survives.
#:
#: It must stay UNDER the SPA's bulk-refresh poll ceiling (30 min in
#: ``frontend/src/modules/monitoring/store.js``). A backend limit above that
#: ceiling turns every slow run into a task the poller abandons while it is
#: still working — the 2026-07-30 failure mode, where harvests that genuinely
#: succeeded were all reported as "did not finish in time".
_DISCOVER_SOFT_TIME_LIMIT_SECONDS: int = 25 * 60


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.discover_workspace",
    bind=True,
    soft_time_limit=_DISCOVER_SOFT_TIME_LIMIT_SECONDS,
    time_limit=_DISCOVER_SOFT_TIME_LIMIT_SECONDS + 60,
    **_TASK_RETRY_KWARGS,
)
def discover_workspace(
    self: Task[object, object], workspace_id: str, days: int = 7
) -> dict[str, object]:
    """Interactive entrypoint: discover ONE workspace's SKUs, then harvest them.

    The single-tenant counterpart of :func:`harvest_all`, and the answer to a
    workspace whose token was set today: its catalogue is empty, so "Refresh
    all SKUs" had no ``nm_id`` to pass to ``monitoring.harvest_sku_window`` and
    answered 404 until the nightly pass ran at 06:00 MSK. Discovery IS the
    refresh for that workspace — the Content API is the only source that can
    say which SKUs exist, and until this task it was reachable from no button.

    Deliberately does NOT take ``_HARVEST_LOCK_NAME``. That lock exists so two
    FLEET walks cannot starve each other of WB's advertising budget; taking it
    here would let one tenant's first click block the nightly harvest for every
    other tenant, and would make this task silently no-op whenever the nightly
    pass happened to be running. The enqueue budget and the in-flight guard on
    the route bound it instead, exactly as they bound ``harvest_sku_window``.

    Args:
        workspace_id: The workspace UUID **as a string** — Celery is configured
            for JSON-only serialization, which has no UUID type.
        days: Rolling window length (default 7 — the funnel-history cap).

    Returns:
        The persisted row counts per metric family, empty when the workspace
        genuinely has no SKUs.

    Raises:
        IntegrationError: If the workspace no longer exists (no credentials to
            discover with), or if discovery failed and it has no SKUs on file.
    """

    async def _run() -> dict[str, object]:
        async with AsyncSessionLocal() as session:
            tokens = await load_workspace_token_bundle(session, uuid.UUID(workspace_id))
        if tokens is None:
            raise IntegrationError(f"Workspace {workspace_id} no longer exists; discovery aborted.")
        # Bound before the first WB call rather than inside the shared helper,
        # which only binds once it knows the SKU list. This task is one tenant
        # from its first line, and a discovery that fails against the Content
        # API must still say whose discovery it was.
        bind_workspace(tokens.workspace_id)
        return dict(
            await _discover_and_harvest_workspace(tokens, days, progress=celery_progress(self))
        )

    return run_task(_run())


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.harvest_all",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def harvest_all(days: int = 7) -> dict[str, int]:
    """Scheduled entrypoint: harvest every workspace's SKUs over the last ``days``.

    Iterates all workspaces with WB tokens stored (encrypted) in the database;
    for each, discovers its full SKU list from the content API with its own
    credentials, then harvests funnel + stock for every SKU and advertising
    for all active/paused campaigns across a rolling window ending yesterday.
    This is the task Celery Beat runs nightly.

    Guarded by a Redis lock so a manual run cannot overlap the nightly one —
    two concurrent harvests would compete for WB's ~1 req/min advertising
    budget and starve each other into retry exhaustion.

    Args:
        days: Rolling window length (default 7 — the funnel-history cap).

    Returns:
        A mapping of persisted row counts per metric family, or
        ``{"skipped_already_running": 1}`` when another harvest holds the lock.
    """
    # A dedicated SYNC client: the shared async client would bind its
    # connection pool to this task's short-lived event loop (the same
    # cross-loop pitfall the engine.dispose() below works around).
    redis = SyncRedis.from_url(settings.redis_url)
    lock = redis.lock(_HARVEST_LOCK_NAME, timeout=_HARVEST_LOCK_TIMEOUT_SECONDS, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("harvest_all skipped: another harvest already holds the lock.")
        redis.close()
        return {"skipped_already_running": 1}

    logger.info("Nightly harvest_all starting (last %d days).", days)

    try:
        return run_task(_discover_and_harvest(days))
    finally:
        try:
            lock.release()
        except LockError:
            # The lock timed out and was re-acquired elsewhere; nothing to do.
            logger.warning("harvest_all lock already expired at release time.")
        redis.close()
