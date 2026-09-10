"""Celery tasks for the ``finreports`` module.

  historical settlement rows price against the tariff that was live then.
  The gate that decides that is :mod:`.freshness`, and it is what makes an
  hourly tick cost one request per workspace on the quiet hours. The same task
  runs once a day with ``reconcile=True``, which re-reads the days behind the
  watermark and ignores the gate — the forward-only walk cannot reach a report
  WB starts serving for days it has already passed.

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
        reconcile: Re-read the days behind the watermark and walk whatever the
            freshness gate says. The daily pass that catches a report WB served
            after our reachable window had already moved past the days it
            covers — see :func:`~src.modules.finreports.tasks.harvest.harvest_all_workspaces`.

    Returns:
        Row counts per source.
    """
    scope = uuid.UUID(workspace_id) if workspace_id else None
    return run_task(harvest_all_workspaces(days=days, workspace_id=scope, reconcile=reconcile))


