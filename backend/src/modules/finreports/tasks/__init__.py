"""Celery tasks for the ``finreports`` module.

* ``finreports.warm_settlement_rollups`` — enqueued when a worker starts, so
  a migration that cleared the rollup is rebuilt off the request path.
* ``finreports.harvest_finance`` — on the hours a report can arrive; pull
  settlement rows for every workspace WB has published an unharvested report
  for. Scheduled ticks first skip every seller
  our own tables show is owed nothing today (:mod:`.harvest.due`); for the rest
  the gate is :mod:`.freshness`. A tick
  also repairs one workspace the gap survey can see a hole in, so a missing week
  is walked within the hour rather than waiting for the night. The same task
  runs once a day with ``reconcile=True`` across every seller, and
  "Refresh" passes it too: both re-read the days behind the coverage and ignore
  the gate — the forward-only walk cannot reach a report WB starts serving for
  days it has already passed.

* ``finreports.harvest_daily_tail`` — hourly; cover the days between the settled
  weekly frontier and yesterday from WB's **daily** realization reports, which
  the weekly lane cannot reach for one to eight days. Provisional by
  construction: it writes rows and its own bookkeeping, never a weekly header
  and never the watermark. See :mod:`.daily_tail`.
* ``finreports.process_settlement_upload`` — enqueued by the upload route; read
  a weekly report the seller uploaded and write what it adds. See
  :mod:`.settlement_upload`.
* ``finreports.verify_daily_tail`` — daily; re-read each of those reports a day
  after harvesting it and record whether WB served the same rows. The one thing
  not yet known about the daily lane, measured rather than assumed.

Both run the async harvest core (:mod:`.harvest`) through
:func:`src.core.tasks.run_task`, which owns the per-task event loop and drains
the shared connection pools afterwards. Calling ``asyncio.run`` directly here is
what left loop-bound connections behind and killed the next scheduled task on
its first query — see that function's docstring.
"""

from __future__ import annotations

import uuid

from src.core.celery_app import celery_app
from src.core.tasks import run_task
from src.modules.finreports.tasks.common import _TASK_RETRY_KWARGS
from src.modules.finreports.tasks.daily_tail import (
    harvest_daily_tail as _harvest_daily_tail,
)
from src.modules.finreports.tasks.daily_tail import (
    verify_daily_tail as _verify_daily_tail,
)
from src.modules.finreports.tasks.harvest import harvest_all_workspaces
from src.modules.finreports.tasks.settlement_upload import (
    UploadNotReadyError,
)
from src.modules.finreports.tasks.settlement_upload import (
    process_settlement_upload as _process_settlement_upload,
)
from src.modules.finreports.tasks.warmup import warm_every_settlement_rollup


@celery_app.task(name="finreports.harvest_finance", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_finance(
    workspace_id: str | None = None, reconcile: bool = False, gated: bool = False
) -> dict[str, int]:
    """Harvest every settlement report WB has formed that a workspace lacks.

    Args:
        workspace_id: A workspace UUID **as a string**, restricting the walk to
            that one tenant; ``None`` sweeps the fleet. A string because Celery
            is configured for JSON-only serialization, which has no UUID.
            "Refresh" passes the caller's own workspace so one tenant's click
            cannot enqueue a walk across every seller on the platform.
        reconcile: Re-read the days behind the coverage and walk whatever the
            freshness gate says. Set by the daily pass and by "Refresh" — both
            are asking to catch a report WB served after our reachable window
            had already moved past the days it covers — see
            :func:`~src.modules.finreports.tasks.harvest.harvest_all_workspaces`.
        gated: Ask WB only about sellers still owed a report today. Set by the
            scheduled ticks and by nothing else.

    Returns:
        Row counts per source.
    """
    scope = uuid.UUID(workspace_id) if workspace_id else None
    return run_task(harvest_all_workspaces(workspace_id=scope, reconcile=reconcile, gated=gated))


@celery_app.task(name="finreports.harvest_daily_tail", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_daily_tail(workspace_id: str) -> dict[str, int]:
    """Cover ONE workspace's days between the settled frontier and yesterday.

    What "Refresh" enqueues. The fleet sweep is not here — it runs inside
    ``finreports.harvest_finance``, after each seller's weekly walk, so the two
    lanes share one lock and one order of spend on the same WB buckets.

    Args:
        workspace_id: A workspace UUID **as a string** — Celery is configured for
            JSON-only serialization, which has no UUID. Required rather than
            optional: a click by one tenant must not spend the WB budget of every
            seller on the platform, and an omitted argument used to mean exactly
            that.

    There is deliberately no span argument. What to cover is not a caller's
    choice — it is whatever lies between what the weekly lane has settled and
    yesterday — and a `days` parameter would invite someone to ask for a month
    of daily reports at one request a minute.

    Returns:
        Reports completed, rows written, and what was skipped.
    """
    return run_task(_harvest_daily_tail(workspace_id=uuid.UUID(workspace_id)))


@celery_app.task(name="finreports.verify_daily_tail", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def verify_daily_tail() -> dict[str, int]:
    """Re-read day-old daily reports and record whether WB changed them.

    Returns:
        How many were re-read, and how many came back unchanged, changed, or
        already superseded by the weekly report covering them.
    """
    return run_task(_verify_daily_tail())


@celery_app.task(  # type: ignore[untyped-decorator]
    name="finreports.process_settlement_upload",
    autoretry_for=(UploadNotReadyError,),
    max_retries=10,
    default_retry_delay=2,
    soft_time_limit=600,
    time_limit=660,
)
def process_settlement_upload(upload_id: str) -> str:
    """Read one uploaded weekly report and write what it adds to the P&L.

    Retried briefly on :class:`UploadNotReadyError`: the route enqueues this before
    its own transaction commits, so the first delivery can arrive to an upload
    that is not there yet. Nothing else is retried — a file that fails to read
    fails the same way twice, and the seller is told why.

    Args:
        upload_id: The upload's UUID as a string; Celery serializes JSON only.

    Returns:
        The status the upload ended in.
    """
    return run_task(_process_settlement_upload(uuid.UUID(upload_id)))


@celery_app.task(  # type: ignore[untyped-decorator]
    name="finreports.warm_settlement_rollups", soft_time_limit=900, time_limit=960
)
def warm_settlement_rollups() -> int:
    """Warm every seller's settlement rollup; enqueued when a worker starts.

    **No retry**: the rollup repairs itself on read, so a failed warm-up costs
    one slow first view, never a wrong figure.

    Returns:
        How many sellers were warmed.
    """
    return run_task(warm_every_settlement_rollup())


from src.modules.finreports.tasks.backfill import backfill_pnl  # noqa: E402

__all__ = [
    "backfill_pnl",
    "harvest_daily_tail",
    "harvest_finance",
    "process_settlement_upload",
    "verify_daily_tail",
    "warm_settlement_rollups",
]
