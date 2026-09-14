"""Celery tasks for the ``guide`` module — one per cadence.

* ``guide.capture_daily`` — the feeds whose window is shorter than a month.
* ``guide.capture_monthly`` — everything WB serves from the account's beginning.

There is no weekly task. One existed briefly for FBS supplies, whose window is
about a month wide; that feed was dropped (see :mod:`src.modules.guide.sources`
for why) and the cadence went with it rather than being kept warm for a future
feed that may never need it.

Three things here exist to keep this module from ever costing the paying
harvests anything, and none of them is the schedule:

* **A soft time limit far below the default.** Every other task may hold one of
  the worker's four slots for an hour. A capture that has not finished in twenty
  minutes is one to cut short and retry next cycle — the data it was reaching
  for is still there next time, which is the entire premise of the module.
* **No autoretry.** The other modules retry on ``IntegrationError`` because a
  missed harvest is money. Here a failure is recorded against the source's
  watermark and re-read on the next cycle, so a retry would only spend WB budget
  sooner. :func:`~src.modules.guide.services.capture.capture_cadence` already
  swallows and records per-source failures; anything reaching Celery is a bug,
  and a bug should be visible rather than retried four times.
* **One lock across both**, held in the service layer — so a monthly run that
  overruns into the daily one's slot makes the daily one a no-op instead of a
  second concurrent walk.

The async body runs through :func:`src.core.tasks.run_task`, which owns the
event loop and drains the pools. Calling ``asyncio.run`` here is what once left
loop-bound connections behind and killed the next scheduled task.
"""

from __future__ import annotations

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.tasks import run_task
from src.modules.guide.services import capture_cadence
from src.modules.guide.sources import GuideCadence

#: Deliberately no ``autoretry_for``: see the module docstring.
_TASK_KWARGS: dict[str, object] = {
    "soft_time_limit": settings.guide_task_soft_time_limit_seconds,
    "time_limit": settings.guide_task_soft_time_limit_seconds + 120,
}


@celery_app.task(name="guide.capture_daily", **_TASK_KWARGS)  # type: ignore[untyped-decorator]
def capture_daily() -> dict[str, int]:
    """Capture the feeds that lose data if a day is missed."""
    return run_task(capture_cadence(GuideCadence.DAILY))


@celery_app.task(name="guide.capture_monthly", **_TASK_KWARGS)  # type: ignore[untyped-decorator]
def capture_monthly() -> dict[str, int]:
    """Capture the feeds WB serves from the account's first sale."""
    return run_task(capture_cadence(GuideCadence.MONTHLY))


__all__ = ["capture_daily", "capture_monthly"]
