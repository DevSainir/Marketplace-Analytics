"""Celery tasks for the ``finreports`` module.

  historical settlement rows price against the tariff that was live then.
  internal workspace, and deliberately NOT part of it. See the task.
  The gate that decides that is :mod:`.freshness`, and it is what makes an
  hourly tick cost one request per workspace on the quiet hours. An hourly tick
  also repairs one workspace the gap survey can see a hole in, so a missing week
  is walked within the hour rather than waiting its turn in the nightly
  rotation. The same task runs once a day with ``reconcile=True``, and
  «Обновить» passes it too: both re-read the days behind the coverage and ignore
  the gate — the forward-only walk cannot reach a report WB starts serving for
  days it has already passed.

* ``finreports.harvest_daily_tail`` — hourly; cover the days between the settled
  weekly frontier and yesterday from WB's **daily** realization reports, which
  the weekly lane cannot reach for one to eight days. Provisional by
  construction: it writes rows and its own bookkeeping, never a weekly header
  and never the watermark. See :mod:`.daily_tail`.
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
from src.core.timeutils import moscow_today
from src.modules.finreports.tasks.common import _TASK_RETRY_KWARGS
from src.modules.finreports.tasks.daily_tail import (
    harvest_daily_tail as _harvest_daily_tail,
)
from src.modules.finreports.tasks.daily_tail import (
    verify_daily_tail as _verify_daily_tail,
)
from src.modules.finreports.tasks.harvest import harvest_all_workspaces




@celery_app.task(name="finreports.harvest_finance", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_finance(
    days: int = 28, workspace_id: str | None = None, reconcile: bool = False
) -> dict[str, int]:

    Args:
        days: How far back to walk.
        workspace_id: A workspace UUID **as a string**, restricting the walk to
            that one tenant; ``None`` sweeps the fleet. A string because Celery
            is configured for JSON-only serialization, which has no UUID.
            «Обновить» passes the caller's own workspace so one tenant's click
            cannot enqueue a walk across every seller on the platform.
        reconcile: Re-read the days behind the coverage and walk whatever the
            freshness gate says. Set by the daily pass and by «Обновить» — both
            are asking to catch a report WB served after our reachable window
            had already moved past the days it covers — see
            :func:`~src.modules.finreports.tasks.harvest.harvest_all_workspaces`.

    Returns:
        Row counts per source.
    """
    scope = uuid.UUID(workspace_id) if workspace_id else None
    return run_task(harvest_all_workspaces(days=days, workspace_id=scope, reconcile=reconcile))


@celery_app.task(name="finreports.harvest_daily_tail", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_daily_tail(workspace_id: str | None = None) -> dict[str, int]:
    """Cover the days between the settled weekly frontier and yesterday.

    Args:
        workspace_id: A workspace UUID **as a string**, restricting the run to
            that one tenant; ``None`` sweeps the fleet. A string because Celery
            is configured for JSON-only serialization, which has no UUID.
            «Обновить» passes the caller's own workspace so one tenant's click
            cannot spend the WB budget of every seller on the platform.

    There is deliberately no span argument. What to cover is not a caller's
    choice — it is whatever lies between what the weekly lane has settled and
    yesterday — and a `days` parameter would invite someone to ask for a month
    of daily reports at one request a minute.

    Returns:
        Reports completed, rows written, and what was skipped.
    """
    scope = uuid.UUID(workspace_id) if workspace_id else None
    return run_task(_harvest_daily_tail(workspace_id=scope))


@celery_app.task(name="finreports.verify_daily_tail", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def verify_daily_tail() -> dict[str, int]:
    """Re-read day-old daily reports and record whether WB changed them.

    Returns:
        How many were re-read, and how many came back unchanged, changed, or
        already superseded by the weekly report covering them.
    """
    return run_task(_verify_daily_tail())



    A task of its own since 2026-09-19, and the separation is the point rather
    than tidiness. It used to be awaited inside `harvest_workspace`, which made
    "best-effort" a claim the code could not keep: the computation re-prices the
    115 366 rows in one allocation — ~269 MB, measured on prod — against a
    768 MiB cgroup whose floor had ratcheted past 550 MB. The kernel killed the
    child mid-run, and a SIGKILL cannot be caught, swallowed or logged by the
    caller that meant the work to be optional. It took the harvest's own outcome
    recording with it and every workspace still queued behind that one. Twenty-
    one hourly harvests died that way inside twenty-four hours and the P&L went
    six days stale.

    Nothing waits on this, so nothing needs it to be inline. As its own task it
    dies alone, and `celery_worker_lost_total` names the warm-up instead of
    blaming the harvest that had already finished.

    **No retry.** The summary is a cache of an answer the read path can always
    recompute, and the next hourly harvest enqueues this again — a retry would
    only spend the same memory sooner.

    Args:
        workspace_id: Workspace UUID as a string; Celery serializes JSON only.
        name: The workspace's display name, for the log line.
    """


from src.modules.finreports.tasks.backfill import backfill_pnl  # noqa: E402

__all__ = [
    "backfill_pnl",
    "harvest_daily_tail",
    "harvest_finance",
    "verify_daily_tail",
]
