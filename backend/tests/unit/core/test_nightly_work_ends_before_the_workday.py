"""Nightly work is finished by 06:30 MSK, half an hour before the working day.

The team starts at 07:00 MSK. Until 2026-09-28 the buyout-cohort pass *started*
at 07:00 and ran to about 07:34, and the monitoring harvest ran 06:00-06:10, so
the first half hour of every working day was spent on the night's work: tables
that were still being rewritten, and a worker busy with it.

So every beat entry that fires between 00:00 and 06:59 — and every firing of
the tasks that prepare the morning's data, wherever someone schedules them —
must, at its measured worst-case runtime, end by 06:30. Entries on a minute
cadence (A/B rotations, the backfill watchdog) are continuous rather than
nightly and are left out; the other daytime entries (from 07:00) are work the
day itself brings — reports WB serves during the day — and are not part of the
night.

The runtimes are measurements, not guesses: the worst ``succeeded in`` of each
task in the worker log over 2026-09-21..28. They grow with the number of
workspaces — the harvest and the cohort pass walk every workspace in turn — so
when one of these is re-measured longer, update it here and let this test say
whether the night still fits.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from celery.schedules import crontab

from src.core.celery_app import celery_app

pytestmark = pytest.mark.unit

#: The latest moment nightly work may still be running.
_DEADLINE = timedelta(hours=6, minutes=30)

#: The working day, from which on an entry is daytime work rather than nightly.
_WORKDAY_STARTS = timedelta(hours=7)

#: Tasks whose whole purpose is the morning's tables: nightly wherever scheduled.
#: The cohort pass sat at 07:00 precisely because a rule keyed only on the clock
#: would have called it daytime work.
_MORNING_PREPARATION = frozenset({"monitoring.harvest_all", "monitoring.refresh_buyout_cohorts"})

#: Worst measured runtime per task, 2026-09-21..28, rounded up to the minute.
_WORST_CASE: dict[str, timedelta] = {
    # 582 s worst for every workspace, walked one after another.
    "monitoring.harvest_all": timedelta(minutes=10),
    # 2 078 s worst; ~22 paced requests per workspace, walked one after another —
    # plus, since 2026-10-02, up to two funnel-gap re-reads per workspace at ~21 s
    # each (`funnel_gaps.MAX_REPAIRS_PER_NIGHT`), ~4 more minutes for six.
    "monitoring.refresh_buyout_cohorts": timedelta(minutes=39),
    # 04:00 reconciliation, 424 s worst.
    "finreports.harvest_finance": timedelta(minutes=8),
    "auth.purge_expired_refresh_tokens": timedelta(minutes=1),
    "guide.capture_daily": timedelta(minutes=1),
    # Monthly, and the one that walks history windows: allowed the whole
    # guide window rather than measured, since it has run twice.
    "guide.capture_monthly": timedelta(minutes=60),
}


#: The host cron entry that fires the database backup, in UTC.
_BACKUP_CRON = (
    Path(__file__).resolve().parents[3] / "scripts" / "backup" / "cron" / "marketplace-backup"
)

#: Moscow has been a fixed UTC+3 since 2014, which is what the cron file relies on too.
_MSK_OFFSET = timedelta(hours=3)

#: Worst measured backup run: 34 min on 2026-09-28, with the reconciliation
#: writing beside it; a quiet night takes about 6, a Sunday rehearsal about 22.
_BACKUP_WORST_CASE = timedelta(minutes=40)


def _nightly_starts() -> list[tuple[str, str, timedelta]]:
    """``(entry, task, start)`` for every nightly firing.

    Nightly: before 07:00, or a task in :data:`_MORNING_PREPARATION` at any hour.
    Minute-cadence entries (every hour of the day) are continuous, not nightly.
    """
    starts: list[tuple[str, str, timedelta]] = []
    for name, entry in celery_app.conf.beat_schedule.items():
        schedule = entry["schedule"]
        assert isinstance(schedule, crontab), f"{name} is not a crontab"
        if len(schedule.hour) == 24:
            continue
        for hour in schedule.hour:
            for minute in schedule.minute:
                start = timedelta(hours=hour, minutes=minute)
                if start < _WORKDAY_STARTS or entry["task"] in _MORNING_PREPARATION:
                    starts.append((name, entry["task"], start))
    return starts


def test_every_nightly_task_has_a_measured_runtime() -> None:
    """A new nightly entry must come with its runtime, or the deadline cannot be checked."""
    unmeasured = sorted({task for _, task, _ in _nightly_starts()} - _WORST_CASE.keys())

    assert unmeasured == [], (
        f"{unmeasured} run at night with no measured runtime here. Measure the "
        "worst `succeeded in` from the worker log and add it to _WORST_CASE."
    )


def test_nightly_work_ends_by_half_past_six() -> None:
    """At its worst measured runtime, nothing scheduled at night is still running at 06:30."""
    late = [
        f"{name} ({task}) {start} + {_WORST_CASE[task]} = {start + _WORST_CASE[task]}"
        for name, task, start in _nightly_starts()
        if task in _WORST_CASE and start + _WORST_CASE[task] > _DEADLINE
    ]

    assert late == [], (
        f"these run into the half hour before the working day: {late}. The team "
        "starts at 07:00 MSK; nightly work must be done by 06:30."
    )


def test_the_cohort_pass_starts_after_the_harvest_has_finished() -> None:
    """The cohort pass only UPDATEs funnel rows, so yesterday's must exist first.

    It skips a ``(date, nm_id)`` with no funnel row rather than inventing one; run
    before the harvest has inserted yesterday, it silently leaves yesterday's
    buyout counts for the next night.
    """
    schedule = celery_app.conf.beat_schedule
    harvest = schedule["nightly-harvest-all"]["schedule"]
    cohorts = schedule["nightly-refresh-buyout-cohorts"]["schedule"]
    harvest_ends = (
        timedelta(hours=min(harvest.hour), minutes=min(harvest.minute))
        + _WORST_CASE["monitoring.harvest_all"]
    )

    cohorts_start = timedelta(hours=min(cohorts.hour), minutes=min(cohorts.minute))

    assert cohorts_start >= harvest_ends


def _backup_starts_msk() -> timedelta:
    """When the host cron fires ``backup.sh``, in Moscow time."""
    for line in _BACKUP_CRON.read_text().splitlines():
        if "backup.sh" in line and not line.lstrip().startswith("#"):
            minute, hour = line.split()[:2]
            return (timedelta(hours=int(hour), minutes=int(minute)) + _MSK_OFFSET) % timedelta(
                days=1
            )
    raise AssertionError(f"no backup.sh entry in {_BACKUP_CRON}")


def test_nothing_nightly_runs_while_the_backup_dumps() -> None:
    """The backup has the database to itself: no nightly entry overlaps its window.

    A reconciliation firing beside pg_dump can push the postgres container past
    its 384 MiB limit; the kernel then kills a backend mid-COMMIT and the dump
    dies with it. The backup is a host cron job, not a
    beat entry, so nothing but this test knows the two share a clock.
    """
    backup_start = _backup_starts_msk()
    backup_end = backup_start + _BACKUP_WORST_CASE
    overlapping = [
        f"{name} ({task}) {start}-{start + _WORST_CASE[task]}"
        for name, task, start in _nightly_starts()
        if task in _WORST_CASE and start < backup_end and backup_start < start + _WORST_CASE[task]
    ]

    assert overlapping == [], (
        f"these run during the backup ({backup_start}-{backup_end} MSK): {overlapping}. "
        "Move them, or the dump competes with them for the database's memory."
    )
