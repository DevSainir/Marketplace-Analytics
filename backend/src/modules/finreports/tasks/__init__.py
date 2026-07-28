"""Celery tasks for the ``finreports`` module.

  historical settlement rows price against the tariff that was live then.

Both run the async harvest core (:mod:`.harvest`) through
:func:`src.core.database.run_task`, which owns the per-task event loop and
drains the shared connection pool afterwards. Calling ``asyncio.run`` directly
here is what left loop-bound connections behind and killed the next scheduled
task on its first query — see that function's docstring.
"""

from __future__ import annotations

from src.core.celery_app import celery_app
from src.core.database import run_task
from src.core.timeutils import moscow_today
from src.modules.finreports.tasks.common import _TASK_RETRY_KWARGS
from src.modules.finreports.tasks.harvest import (
    harvest_all_workspaces,
)




@celery_app.task(name="finreports.harvest_finance", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_finance(days: int = 28) -> dict[str, int]:
    return run_task(harvest_all_workspaces(days=days))


