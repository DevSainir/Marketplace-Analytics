"""The review history runs in an hour of its own.

It earns nothing on the day it runs, so it must never be the reason paying work
waited for a worker slot or a share of the worker's 768 MiB. The rule is pinned
on the schedule itself: no other scheduled entry starts while it may still be
running. Minute-cadence entries (A/B rotations, the backfill watchdog) are
continuous and light, and are left out — as the nightly-deadline test does.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from celery.schedules import crontab

from src.core.celery_app import celery_app

pytestmark = pytest.mark.unit

_ENTRY = "evening-snapshot-reviews"

#: Generous for today's fleet: the largest workspace's walk is ~150 paced pages,
#: and the storefront reads one card group every three seconds across all of them.
_WORST_CASE = timedelta(minutes=45)


def _starts(entry: dict[str, object]) -> list[timedelta]:
    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    return [
        timedelta(hours=hour, minutes=minute)
        for hour in schedule.hour
        for minute in schedule.minute
    ]


def test_the_review_history_runs_once_a_day_outside_the_night() -> None:
    """Daily, and after 07:00: the night belongs to the harvests that prepare the morning."""
    starts = _starts(celery_app.conf.beat_schedule[_ENTRY])

    assert len(starts) == 1
    assert starts[0] >= timedelta(hours=7)


def test_nothing_else_starts_while_the_review_history_may_still_be_running() -> None:
    (start,) = _starts(celery_app.conf.beat_schedule[_ENTRY])
    window_end = start + _WORST_CASE

    clashes = [
        f"{name} at {other}"
        for name, entry in celery_app.conf.beat_schedule.items()
        if name != _ENTRY and len(entry["schedule"].hour) != 24
        for other in _starts(entry)
        if start <= other < window_end
    ]

    assert clashes == []
