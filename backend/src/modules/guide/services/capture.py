"""The orchestrator: run one cadence's sources across the fleet, politely.

Everything about "must not disturb the paying harvests" that is not a schedule
lives here:

* **One lock for both cadences.** They are scheduled apart, but a monthly run
  that overruns must not meet the daily one — two guide runs at once is two
  worker slots the harvest cannot have.
* **A failure is per source, per workspace.** One WB outage, one missing token
  or one malformed feed must not cost the other ten their run, so every walk is
  caught and recorded rather than raised.
* **A failed walk does not move its watermark.** The next run re-reads instead
  of stepping over the gap, which is the whole difference between a late
  capture and a missing one.
* **The rate gates are the surface's own.** The buckets are keyed per endpoint,
  so these calls queue against themselves and not against the funnel, the
  settlement walk or fullstats — see :func:`_gate_for`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

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
    statistics_rate_gate,
)
from src.modules.guide.repos import GuideRepository
from src.modules.guide.services.fetch import CaptureWindow
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
_SHARED_GATES: dict[str, Callable[[Settings, str], RateGate]] = {
    "wb_analytics_base_url": lambda s, token: analytics_rate_gate(s, token=token),
    "wb_statistics_base_url": lambda s, token: statistics_rate_gate(s, token=token),
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
                message="нет токена нужной категории",
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

    try:
        async with WBReferenceClient(
            config,
            base_url=source.host(config),
            token=token,
            rate_gate=_gate_for(source, token=token, config=config),
        ) as client:
            result = await source.fetch(client, window)
    except (IntegrationError, ValueError, KeyError, TypeError) as exc:
        # Recorded, never raised: one bad feed must not cost the other ten their
        # run, and the watermark stays where it was so the next run re-reads.
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("guide: %s failed for %s (%s).", source.key, bundle.name, message[:200])
        async with AsyncSessionLocal() as session:
            await GuideRepository(session).record_run(
                source=source.key,
                workspace_id=workspace_id,
                status="failed",
                rows=0,
                cursor=cursor,
                captured_through=captured_through,
                message=message,
            )
            await session.commit()
        return "failed", 0, message

    async with AsyncSessionLocal() as session:
        repo = GuideRepository(session)
        stored = await repo.upsert_records(
            source=source.key, workspace_id=workspace_id, rows=result.rows
        )
        await repo.record_run(
            source=source.key,
            workspace_id=workspace_id,
            status="ok" if stored else "empty",
            rows=stored,
            cursor=result.cursor if result.cursor is not None else cursor,
            captured_through=(
                result.captured_through if result.captured_through is not None else captured_through
            ),
        )
        await session.commit()
    return ("ok" if stored else "empty"), stored, ""


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
