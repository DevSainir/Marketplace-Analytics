"""Scheduled live-position refresh for pinned search phrases.

Deliberately NOT part of ``monitoring.harvest_all``, even though one of its three
daily runs starts at the same moment:

* **Different host, different budget.** The harvest talks to the authenticated
  seller APIs; this talks to the public storefront (``search.wb.ru``), which
  meters a separate ~1 req/min per-IP bucket. Sharing a task would make one
  surface's throttling delay the other's for no reason.
* **Different transactions.** The harvest's phases commit their own work; so does
  this, once per phrase. A run interrupted at phrase 12 keeps the eleven results
  it already paid WB's rate budget for.
* **Different failure meaning.** A missing funnel row is a data gap; a missing
  position is just "WB throttled us, ask again in eight hours". Folding this into
  the harvest would let the latter fail a run that otherwise succeeded.

**One scan answers for many SKUs.** Pins are grouped by phrase, and the probe
reads whole result pages, so it looks for the workspace's entire catalogue in the
pages it already fetched: ten SKUs pinned to «носки мужские» cost one scan, not
ten. This is the whole reason the run is affordable three times a day.

**Pacing is the point, not politeness.** Phrases are probed sequentially with a
deliberate gap (``wb_search_probe_spacing_seconds``) because back-to-back
requests to this host are answered 429 even one per 25 s. A run that hurries
returns nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from redis import Redis as SyncRedis
from redis.exceptions import LockError

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.integrations.wildberries import build_search_client
from src.modules.monitoring.repos import PinnedKeywordRepository, ProductCardRepository
from src.modules.monitoring.tasks.common import _TASK_RETRY_KWARGS
from src.modules.workspaces.contract import load_workspace_token_bundles

logger = get_logger(__name__)

#: Distributed-lock name. Separate from the harvest's: the two are meant to be
#: able to run at once (different WB hosts), and only position runs must not
#: overlap each other — a manual «Проверить все позиции» landing on top of the
#: scheduled run would double the request rate against the one bucket that
#: cannot take it.
_POSITIONS_LOCK_NAME = "monitoring:refresh_pinned_positions:lock"

#: Ceiling on one run, derived from the pacing: at 60 s a phrase, 60 phrases is
#: an hour, which is as long as a scheduled run may reasonably hold its lock.
_POSITIONS_LOCK_TIMEOUT_SECONDS = 2 * 60 * 60


async def _probe_workspace_pins(workspace_id: uuid.UUID, name: str) -> dict[str, int]:
    """Re-probe every phrase pinned to one workspace's SKUs.

    Args:
        workspace_id: The workspace whose pins to refresh.
        name: Its display name, for the log line.

    Returns:
        Counters: phrases probed, pins updated, phrases WB withheld, and phrases
        dropped by the per-run ceiling.
    """
    async with AsyncSessionLocal() as session:
        pins = await PinnedKeywordRepository(session).list_for_workspace(workspace_id=workspace_id)
        catalogue = await ProductCardRepository(session).list_workspace_nm_ids(workspace_id)
    if not pins:
        return {"phrases": 0, "pins_updated": 0, "phrases_failed": 0, "phrases_skipped": 0}

    by_keyword: dict[str, list[int]] = defaultdict(list)
    for pin in pins:
        by_keyword[pin.keyword].append(pin.nm_id)
    phrases = sorted(by_keyword)

    # A silent truncation would read as "everything is current" on cards that are
    # in fact stale, so the ceiling is logged whenever it bites.
    ceiling = settings.wb_search_max_keywords_per_run
    skipped = max(0, len(phrases) - ceiling)
    if skipped:
        logger.warning(
            "Workspace '%s' has %d pinned phrases; probing the first %d this run "
            "(wb_search_max_keywords_per_run). %d phrase(s) keep their previous position.",
            name,
            len(phrases),
            ceiling,
            skipped,
        )
        phrases = phrases[:ceiling]

    wanted = set(catalogue)
    counts = {"phrases": 0, "pins_updated": 0, "phrases_failed": 0, "phrases_skipped": skipped}
    async with build_search_client(settings) as client:
        for index, keyword in enumerate(phrases):
            if index:
                await asyncio.sleep(settings.wb_search_probe_spacing_seconds)
            try:
                probe = await client.find_positions(
                    query=keyword, nm_ids=wanted | set(by_keyword[keyword])
                )
            except IntegrationError as exc:
                # One throttled phrase must not cost the run the rest of its
                # phrases: the pin keeps its previous number and its old
                # timestamp, which is what tells the seller it is stale.
                logger.warning("Position probe for %r failed (%s); leaving its pins.", keyword, exc)
                counts["phrases_failed"] += 1
                continue
            counts["phrases"] += 1
            found = {position.nm_id: position for position in probe.positions}
            checked_at = datetime.now(UTC)
            # Its own session per phrase: the run spans minutes of paced WB
            # calls, and holding one transaction across them would pin a
            # connection for the whole run and lose every result if the last
            # phrase failed.
            async with AsyncSessionLocal() as session:
                repo = PinnedKeywordRepository(session)
                for nm_id in by_keyword[keyword]:
                    position = found.get(nm_id)
                    await repo.record_probe(
                        nm_id=nm_id,
                        keyword=keyword,
                        normalized_query=probe.normalized_query,
                        position=position.position if position else None,
                        positions_scanned=probe.positions_scanned,
                        total_found=probe.total_found,
                        truncated=probe.truncated,
                        checked_at=checked_at,
                    )
                    counts["pins_updated"] += 1
                await session.commit()
    return counts


async def _refresh_pinned_positions(workspace_id: uuid.UUID | None) -> dict[str, int]:
    """Refresh pinned positions for one workspace, or for every workspace.

    Args:
        workspace_id: A single workspace, or ``None`` for all of them (the
            scheduled run).

    Returns:
        Counters summed across the workspaces visited.
    """
    async with AsyncSessionLocal() as session:
        bundles = await load_workspace_token_bundles(session)
    if workspace_id is not None:
        bundles = [bundle for bundle in bundles if bundle.workspace_id == workspace_id]
    if not bundles:
        logger.warning("No workspace to refresh positions for.")
        return {"workspaces": 0, "phrases": 0, "pins_updated": 0}

    totals: dict[str, int] = {"workspaces": 0}
    for bundle in bundles:
        try:
            result = await _probe_workspace_pins(bundle.workspace_id, bundle.name)
        except Exception as exc:  # isolate workspaces from each other
            logger.warning("Position refresh failed for workspace '%s': %s", bundle.name, exc)
            continue
        totals["workspaces"] += 1
        for key, value in result.items():
            totals[key] = totals.get(key, 0) + value
    return totals


@celery_app.task(  # type: ignore[untyped-decorator]
    name="monitoring.refresh_pinned_positions",
    bind=False,
    **_TASK_RETRY_KWARGS,
)
def refresh_pinned_positions(workspace_id: str | None = None) -> dict[str, int]:
    """Re-check the live WB position of every pinned phrase.

    Runs three times a day on the schedule (see ``celery_app.beat_schedule``) and
    on demand behind «Проверить все позиции». WB publishes no position history,
    so these samples are the only record there will ever be of how a card moved —
    but each is only as good as its timestamp, which is why the cards show one.

    Guarded by its own Redis lock: a manual run landing on top of the scheduled
    one would double the request rate against a bucket that already refuses
    back-to-back requests. The harvest's lock is deliberately NOT reused — the
    two tasks talk to different hosts and are meant to overlap.

    Args:
        workspace_id: Refresh only this workspace (the manual trigger passes the
            caller's), or ``None`` to walk every workspace (the schedule).

    Returns:
        Counters per family, or ``{"skipped_already_running": 1}`` when another
        position run holds the lock.
    """
    redis = SyncRedis.from_url(settings.redis_url)
    lock = redis.lock(_POSITIONS_LOCK_NAME, timeout=_POSITIONS_LOCK_TIMEOUT_SECONDS, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("refresh_pinned_positions skipped: another position run holds the lock.")
        redis.close()
        return {"skipped_already_running": 1}

    scope = workspace_id or "all workspaces"
    logger.info("Pinned-position refresh starting (%s).", scope)
    try:
        return run_task(
            _refresh_pinned_positions(uuid.UUID(workspace_id) if workspace_id else None)
        )
    finally:
        try:
            lock.release()
        except LockError:
            logger.warning("refresh_pinned_positions lock already expired at release time.")
        redis.close()
