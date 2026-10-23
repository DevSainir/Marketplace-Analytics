"""The orchestrator: run one cadence's sources across the fleet, politely.

Everything about "must not disturb the paying harvests" that is not a schedule
lives here:

* **One lock for both cadences.** They are scheduled apart, but a monthly run
  that overruns must not meet the daily one — two guide runs at once is two
  worker slots the harvest cannot have.
* **A failure is per source, per workspace.** One WB outage, one missing token
  or one malformed feed must not cost the other ten their run, so every walk is
  caught and recorded rather than raised.
* **A failed walk keeps the watermark its committed batches earned, and not one
  step further.** The rows a run stored before it died are real, so re-reading
  them buys nothing; what must never happen is the watermark passing a row that
  was never stored. That is why a batch carries the watermark it makes safe
  rather than the walk announcing one at the end — and why a stream that cannot
  name a safe point mid-page simply does not carry one (see
  :class:`~src.modules.guide.services.fetch.common.CaptureBatch`).
* **The rate gates are the surface's own.** The buckets are keyed per endpoint,
  so these calls queue against themselves and not against the funnel, the
  settlement walk or fullstats — see :func:`_gate_for`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from sqlalchemy.exc import SQLAlchemyError

from src.core.config import Settings, settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.locks import single_flight
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.timeutils import moscow_today
from src.integrations.wildberries.clients.reference import WBReferenceClient
from src.integrations.wildberries.rate_limit import (
    NullRateGate,
    RateGate,
    analytics_rate_gate,
    catalogue_rate_gate,
    feedbacks_rate_gate,
    statistics_rate_gate,
)
from src.modules.guide.repos import GuideRepository
from src.modules.guide.services.fetch import CaptureBatch, CaptureWindow
from src.modules.guide.sources import GuideCadence, GuideSource, sources_for
from src.modules.workspaces.contract import WorkspaceTokenBundle, load_workspace_token_bundles

logger = get_logger(__name__)

#: One lock for every cadence: see the module docstring. Sized well above any
#: single run (the soft time limit cuts a run off at twenty minutes) so a live
#: holder keeps it, and low enough that a killed worker frees it within minutes.
_LOCK_KEY = "guide:capture"
_LOCK_TTL_SECONDS = 120.0

#: Hosts whose bucket a paying harvest also uses. Anything not here is a surface
#: only this module touches, and an unpaced call on it can inconvenience nobody
#: but us — WB's own limits there are 5-10 requests a second and one run makes a
#: handful. The marketplace host belonged here while FBS supplies were captured;
#: it left with them, and any future source on that host must put it back.
#: `common` was added on 2026-09-29, while a harvest still used that host; none
#: does now, and the gate stays because pacing an unshared host costs nothing.
#: tests/unit/guide/test_capture_pacing.py derives which hosts must be here.
_SHARED_GATES: dict[str, Callable[[Settings, str], RateGate]] = {
    "wb_analytics_base_url": lambda s, token: analytics_rate_gate(s, token=token),
    "wb_statistics_base_url": lambda s, token: statistics_rate_gate(s, token=token),
    "wb_common_base_url": lambda s, token: catalogue_rate_gate(s, token=token, surface="common"),
    # Since 2026-10-02 the daily review history (monitoring) walks this host too.
    "wb_feedbacks_base_url": lambda s, token: feedbacks_rate_gate(s, token=token),
}


def _gate_for(source: GuideSource, *, token: str, config: Settings) -> RateGate:
    """The pacing gate this source's host deserves.

    The shared surfaces get the same gate their harvest uses. That is not
    a courtesy — the bucket is keyed ``(surface, endpoint, token)``, so sharing
    the FACTORY is what puts a guide call in its own endpoint's bucket beside
    the harvest's rather than in a second, competing one.
    """
    build = _SHARED_GATES.get(source.base_url)
    return build(config, token) if build else NullRateGate()


async def _capture_one(
    source: GuideSource,
    bundle: WorkspaceTokenBundle,
    *,
    config: Settings,
) -> tuple[str, int, str]:
    """Walk one source for one workspace and persist whatever it returned.

    Returns:
        ``(status, rows, message)`` — already recorded against the watermark.
    """
    token = source.token_for(bundle)
    workspace_id = bundle.workspace_id
    if not token:
        async with AsyncSessionLocal() as session:
            await GuideRepository(session).record_run(
                source=source.key,
                workspace_id=workspace_id,
                status="skipped",
                rows=0,
                cursor=None,
                captured_through=None,
                message="no token of the required scope",
            )
            await session.commit()
        return "skipped", 0, "no token"

    async with AsyncSessionLocal() as session:
        run = await GuideRepository(session).load_run(source=source.key, workspace_id=workspace_id)
        cursor = run.cursor if run else None
        captured_through = run.captured_through if run else None

    today = moscow_today()
    window = CaptureWindow(
        today=today,
        cursor=cursor,
        captured_through=captured_through,
        floor=today - timedelta(days=config.guide_history_days),
        max_windows=config.guide_max_windows_per_run,
        max_pages=config.guide_max_pages_per_run,
        max_rows=config.guide_max_rows_per_run,
    )

    mark = _Watermark(cursor=cursor, captured_through=captured_through, rows=0)
    try:
        async with WBReferenceClient(
            config,
            base_url=source.host(config),
            token=token,
            rate_gate=_gate_for(source, token=token, config=config),
        ) as client:
            async for batch in source.fetch(client, window):
                mark = await _store(
                    source=source, workspace_id=workspace_id, batch=batch, mark=mark
                )
    except (IntegrationError, SQLAlchemyError, ValueError, KeyError, TypeError) as exc:
        # Recorded, never raised: one bad feed must not cost the other ten their
        # run. What the walk had already stored stays stored, and the watermark
        # stays at the last point every row behind it was written.
        #
        # `SQLAlchemyError` joined the list on 2026-09-17, when it was the one
        # that got away. A walk writes as it goes now, so a row WB serves in a
        # shape the column will not take raises from the insert rather than from
        # the parse — and a `StatementError` is none of the four exceptions this
        # used to catch. It escaped `_capture_one`, killed the whole task, and
        # the five feeds after it in the cadence never ran. Catching the parse
        # errors but not the storage ones only ever held while fetching and
        # storing were separate phases.
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("guide: %s failed for %s (%s).", source.key, bundle.name, message[:200])
        async with AsyncSessionLocal() as session:
            await GuideRepository(session).record_run(
                source=source.key,
                workspace_id=workspace_id,
                status="failed",
                rows=mark.rows,
                cursor=mark.cursor,
                captured_through=mark.captured_through,
                message=message,
            )
            await session.commit()
        return "failed", mark.rows, message

    if mark.rows == 0:
        # An empty walk still records a run: "we asked and there was nothing" is
        # a different state from "nobody has asked", and only the row says which.
        async with AsyncSessionLocal() as session:
            await GuideRepository(session).record_run(
                source=source.key,
                workspace_id=workspace_id,
                status="empty",
                rows=0,
                cursor=mark.cursor,
                captured_through=mark.captured_through,
            )
            await session.commit()
        return "empty", 0, ""
    return "ok", mark.rows, ""


class _Watermark(NamedTuple):
    """How far a walk has got, as the database now records it.

    Attributes:
        cursor: Resume point for the next run.
        captured_through: Last day fully covered.
        rows: Rows stored so far this run, carried because `guide_run.rows`
            describes the RUN and each batch only knows about itself.
    """

    cursor: str | None
    captured_through: date | None
    rows: int


async def _store(
    *,
    source: GuideSource,
    workspace_id: uuid.UUID,
    batch: CaptureBatch,
    mark: _Watermark,
) -> _Watermark:
    """Commit one batch and the watermark it earned, in one transaction.

    Together, and that is the point: rows written without the watermark are
    re-read next run (merely wasteful), while a watermark written without its
    rows steps over them for good. One transaction makes the pair impossible to
    get out of step, whatever kills the process next.

    Args:
        source: The feed being walked.
        workspace_id: Owning tenant.
        batch: What the walk just produced.
        mark: Where the walk stood before it.

    Returns:
        The updated watermark.
    """
    moved = _Watermark(
        cursor=batch.cursor if batch.cursor is not None else mark.cursor,
        captured_through=(
            batch.captured_through if batch.captured_through is not None else mark.captured_through
        ),
        rows=mark.rows + len(batch.rows),
    )
    async with AsyncSessionLocal() as session:
        repo = GuideRepository(session)
        await repo.upsert_records(source=source.key, workspace_id=workspace_id, rows=batch.rows)
        await repo.record_run(
            source=source.key,
            workspace_id=workspace_id,
            status="ok" if moved.rows else "empty",
            rows=moved.rows,
            cursor=moved.cursor,
            captured_through=moved.captured_through,
        )
        await session.commit()
    return moved


async def capture_cadence(
    cadence: GuideCadence, *, config: Settings | None = None
) -> dict[str, int]:
    """Walk every source of one cadence, for every harvestable workspace.

    The tenant list comes from ``load_workspace_token_bundles``, which already
    drops an organisation past its grace window — enumerate workspaces any other
    way and this module would spend WB budget for a tenant that stopped paying.

    Args:
        cadence: Which schedule is running.
        config: Settings override, for tests.

    Returns:
        Rows captured per source key. Empty when the capture is switched off or
        another guide run already holds the lock.
    """
    active = config or settings
    if not active.guide_capture_enabled:
        logger.info("guide: capture disabled, %s run is a no-op.", cadence.value)
        return {}

    async with single_flight(_LOCK_KEY, ttl_seconds=_LOCK_TTL_SECONDS, redis=get_redis()) as held:
        if not held:
            logger.info("guide: another capture holds the lock, skipping %s.", cadence.value)
            return {}

        async with AsyncSessionLocal() as session:
            bundles = await load_workspace_token_bundles(session)

        captured: dict[str, int] = {}
        for source in sources_for(cadence):
            total = 0
            for bundle in bundles:
                _status, rows, _message = await _capture_one(source, bundle, config=active)
                total += rows
            captured[source.key] = total
            logger.info("guide: %s captured %d rows across the fleet.", source.key, total)
        return captured


__all__ = ["capture_cadence"]
