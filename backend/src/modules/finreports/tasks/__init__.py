"""Celery tasks for the ``finreports`` module.

  historical settlement rows price against the tariff that was live then.

Both run the async harvest core (:mod:`.harvest`) under ``asyncio.run``.
"""

from __future__ import annotations

import asyncio

from src.core.celery_app import celery_app
from src.core.timeutils import moscow_today
from src.modules.finreports.tasks.common import _TASK_RETRY_KWARGS
from src.modules.finreports.tasks.harvest import (
    harvest_all_workspaces,
)




@celery_app.task(name="finreports.harvest_finance", **_TASK_RETRY_KWARGS)  # type: ignore[untyped-decorator]
def harvest_finance(days: int = 28) -> dict[str, int]:
    return asyncio.run(harvest_all_workspaces(days=days))


