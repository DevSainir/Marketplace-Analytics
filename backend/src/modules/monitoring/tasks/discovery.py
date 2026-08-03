"""The nightly all-workspace harvest: discover SKUs, then harvest each workspace."""

from __future__ import annotations

from datetime import timedelta

from redis import Redis as SyncRedis
from redis.exceptions import LockError

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBContentClient
from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.repos import ProductCardRepository
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.monitoring.tasks.harvest import _harvest_sku_window
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)

#: Distributed-lock name preventing overlapping full harvests (the WB
#: advertising surface allows ~1 req/min — two concurrent harvests starve
#: each other into retry exhaustion).
_HARVEST_LOCK_NAME = "monitoring:harvest_all:lock"

#: Generous ceiling on one harvest run; the lock auto-expires after this so a
#: crashed worker can never wedge the nightly schedule permanently.
_HARVEST_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60


async def _discover_and_harvest_workspace(
    tokens: WorkspaceTokenBundle, days: int
) -> dict[str, int]:
    """Discover one workspace's SKUs and harvest a rolling ``days``-day window.

    Discovery runs with the workspace's own Analytics token against the
    Content API, so the resulting cards — and everything harvested for them —
    are provably that workspace's SKUs.

    Args:
        tokens: The workspace's decrypted WB credentials.
        days: Length of the inclusive window ending yesterday (Moscow time).

    Returns:
        A mapping of persisted row counts per metric family.

    Raises:
        IntegrationError: If the workspace has no analytics token (discovery
            is impossible without it) or discovery itself fails.
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
        if not tokens.content:
            raise IntegrationError(
                f"Workspace '{tokens.name}' has no content/analytics token; "
                "cannot discover its SKUs."
            )
        async with WBContentClient(settings, token=tokens.content) as content:
            fetched = await content.fetch_all_cards()
        nm_ids = [card.nm_id for card in fetched]
        cards = fetched
    logger.info(
        "Discovered %d SKUs for workspace '%s'.",
        len(nm_ids),
        tokens.name,
    )
    if not nm_ids:
        return {}

    end = moscow_today() - timedelta(days=1)  # WB serves no current-day data
    start = end - timedelta(days=days - 1)
    outcome = await _harvest_sku_window(
        tokens=tokens, nm_ids=nm_ids, date_from=start, date_to=end, cards=cards
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
            result = await _discover_and_harvest_workspace(bundle, days)
        except Exception as exc:  # isolate workspaces from each other
            logger.warning("Harvest failed for workspace '%s': %s", bundle.name, exc)
            failures.append(bundle.name)
            totals["workspaces_failed"] += 1
            continue
        totals["workspaces_harvested"] += 1
        for key, value in result.items():
            totals[key] = totals.get(key, 0) + value

    if totals["workspaces_harvested"] == 0:
        raise IntegrationError(f"Every workspace harvest failed ({', '.join(failures)}); see logs.")
    return totals


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
