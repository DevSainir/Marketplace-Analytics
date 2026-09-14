"""Bounds for the `guide` capture module.

Every value here exists to keep a module that earns nothing from costing
anything. The capture runs off-peak on a worker whose four slots the paying
harvests share, so the questions these answer are "how long may one run hold a
slot" and "how much may it ask WB for in one go" — not "how fast can we
backfill".
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class GuideSettings(BaseSettings):
    """Cadence-independent bounds on the reference capture."""

    #: Master switch. ``False`` leaves the schedule in place and makes every run
    #: a no-op — the knob to reach for when the worker is under pressure and
    #: something has to give, because this is the thing that may give.
    guide_capture_enabled: bool = True

    #: How many 31-day windows one monthly run walks per source, per workspace.
    #: The windowed feeds serve the account's whole history, so the first runs
    #: are a backfill: at 12 windows a run, roughly a year of history per month,
    #: and a three-year account is caught up within three runs. Raising it
    #: lengthens one run rather than making the backfill cheaper — the analytics
    #: bucket refills one token per ~20 s whatever this says.
    guide_max_windows_per_run: int = 12

    #: How far back a first run reaches before it starts walking forward.
    #: WB serves these feeds from the account's first sale, so this is a bound
    #: on OUR appetite, not on WB's memory: three years covers every workspace
    #: on the platform today (the oldest first settlement is 2024-01-29).
    guide_history_days: int = 1100

    #: Pages of the orders stream one run will walk. WB caps a response at
    #: 80 000 rows and the walk resumes from the last row's ``lastChangeDate``,
    #: so a daily run needs one page and this only matters after an outage.
    #: Eight pages is ~640 000 rows, comfortably the whole 188-day window for
    #: any account we have.
    guide_max_pages_per_run: int = 8

    #: Rows of a take/skip feed (reviews, questions) one run captures. The
    #: biggest account has 135 099 reviews; at this size a monthly run walks
    #: about a fifth of that and the watermark carries the rest forward.
    guide_max_rows_per_run: int = 30000

    #: Seconds one cadence's whole run may take before Celery raises inside it.
    #: Far below the hour every other task may hold a slot for: a capture that
    #: has not finished in twenty minutes is one to cut short and retry next
    #: cycle, never one to let sit on a worker slot the harvest needs.
    guide_task_soft_time_limit_seconds: int = Field(default=1200, ge=60)


__all__ = ["GuideSettings"]
