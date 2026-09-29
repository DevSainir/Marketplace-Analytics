"""Integration tests for the Celery task registry and beat schedule.

Celery resolves tasks by **name string**, so nothing in Python catches a
schedule entry that points at a task nobody registered — it fails silently at
3 a.m., every night, with the harvest simply never running. These tests close
that gap by checking the registry the worker actually builds.

No broker connection is made: importing the app is enough to populate the
registry and the schedule.
"""

from __future__ import annotations

from typing import Any

import pytest
from celery.schedules import crontab

from src.core.celery_app import celery_app

#: Every task the platform relies on, by the name callers and beat use.
EXPECTED_TASKS: list[str] = [
    "monitoring.harvest_all",
    "monitoring.harvest_sku_window",
    "monitoring.refresh_buyout_cohorts",
    "monitoring.carry_day_headers",
    "monitoring.top_up_customer_prices",
    "auth.purge_expired_refresh_tokens",
    # Enqueued by the harvest, never scheduled — so beat's own check below
    # cannot see it, and a rename would silently stop the cache being warmed
    # while everything kept reporting success. It is listed here for exactly
    # that reason: it is the one finreports task with no schedule behind it.
    # Also unscheduled: the worker's start hook sends it by name.
    "finreports.warm_settlement_rollups",
    # The history backfill. Its lanes are chains of self-enqueueing ticks, and
    # the watchdog restarts them BY NAME — so a rename that skipped either side
    # leaves a dead lane with nothing scheduled to notice, which is exactly the
    # silent failure this file exists to catch.
    "monitoring.backfill_catalogue",
    "monitoring.backfill_funnel",
    "monitoring.backfill_advertising",
    "finreports.backfill_pnl",
    "workspaces.sweep_stalled_backfills",
    # The reference capture. It earns nothing, which is exactly why a silently
    # unregistered task here would go unnoticed for months — and the feeds it
    # walks are the ones WB deletes on a schedule.
    "guide.capture_daily",
    "guide.capture_monthly",
]


@pytest.fixture(scope="module", autouse=True)
def _load_task_modules() -> None:
    """Import every module that registers tasks.

    In production the worker autodiscovers these; in-process we import them so
    the registry under test is the same one the worker builds.
    """
    import src.modules.ab_tests.tasks
    import src.modules.finreports.tasks
    import src.modules.guide.tasks
    import src.modules.monitoring.tasks
    import src.modules.users.tasks
    import src.modules.workspaces.tasks  # noqa: F401


@pytest.mark.parametrize("task_name", EXPECTED_TASKS)
def test_task_is_registered_under_its_public_name(task_name: str) -> None:
    """A renamed task with a stale ``name=`` breaks every caller silently."""
    assert task_name in celery_app.tasks


def test_every_scheduled_entry_points_at_a_real_task() -> None:
    """Beat cannot enqueue a task that is not registered.

    This is the failure that produces "the nightly harvest stopped running" with
    nothing in the application logs.
    """
    scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}

    unregistered = sorted(scheduled - set(celery_app.tasks))

    assert unregistered == [], f"Beat schedules unregistered tasks: {unregistered}"


def test_the_schedule_runs_on_moscow_time() -> None:
    """WB dates all data by the Moscow day, so beat must too.

    On a UTC server a 06:00 crontab would fire at 09:00 MSK — after the team
    has already opened the dashboard expecting fresh numbers.
    """
    assert celery_app.conf.timezone == "Europe/Moscow"


def test_the_nightly_harvest_precedes_the_dependent_jobs() -> None:
    """Ordering is a real dependency, not a formatting preference.

    The cohort refresh and the finance harvest read what the harvest wrote and
    compete for the same rate-limited WB surfaces; running them first would
    both starve the harvest and compute against yesterday's data.

    Compared to the minute, not the hour: since 2026-09-28 both sit in 05:00 so
    the night ends by 06:30. That the cohort pass also waits out the harvest's
    worst runtime is ``tests/unit/core/test_nightly_work_ends_before_the_workday.py``.
    """
    schedule = celery_app.conf.beat_schedule
    harvest = schedule["nightly-harvest-all"]["schedule"]
    cohorts = schedule["nightly-refresh-buyout-cohorts"]["schedule"]

    assert (min(harvest.hour), min(harvest.minute)) < (min(cohorts.hour), min(cohorts.minute))


def test_the_price_top_up_finishes_before_the_day_rolls_over() -> None:
    """The order feed serves today's price, not a history of it.

    A top-up that fires after midnight asks about a day it can no longer
    answer for: it walks every workspace, fills nothing, and logs success.
    That is what happened on 2026-09-23, when the pass ran at 06:51 MSK and
    topped up 0 of 286 — so the hour is a correctness property, not a
    preference.
    """
    entry = celery_app.conf.beat_schedule["evening-top-up-customer-prices"]["schedule"]

    assert max(entry.hour) == 23
    assert max(entry.minute) < 60


def _finance_ticks() -> dict[str, Any]:
    """Every scheduled finance harvest except the nightly reconciliation."""
    return {
        name: entry
        for name, entry in celery_app.conf.beat_schedule.items()
        if entry["task"] == "finreports.harvest_finance"
        and not entry.get("kwargs", {}).get("reconcile")
    }


def test_every_scheduled_finance_tick_is_gated() -> None:
    """A scheduled tick asks WB only about sellers still owed a report today.

    Ungated, each one spends two `list` requests per seller to learn nothing on
    most runs — 58 runs a day found two or three reports. The gate is a keyword
    the task defaults off, so an entry that forgets it silently goes back to
    asking about everybody.
    """
    ticks = _finance_ticks()

    assert ticks
    assert all(entry.get("kwargs", {}).get("gated") is True for entry in ticks.values())


def test_the_nightly_reconciliation_is_never_gated() -> None:
    """The pass that catches off-calendar reports must ask WB about everyone.

    The gate trusts the calendar; a report served days late or back-dated
    (983241109, stamped 01.09 and first served 09.09) is exactly what it cannot
    see, and the reconciliation is the only pass left that looks.
    """
    entry = celery_app.conf.beat_schedule["daily-finreports-reconcile"]

    assert entry["kwargs"] == {"reconcile": True}


def test_yesterday_s_daily_report_is_asked_for_after_midnight() -> None:
    """WB serves the daily report in the small hours: 01:01, 03:06, 04:01.

    Hour 04 is the reconciliation's, which walks every new report as well as the
    old ones; hour 03 is nobody's, because it is the database backup's.
    """
    schedule = celery_app.conf.beat_schedule
    hours = set(schedule["finreports-harvest-at-night"]["schedule"].hour)
    hours |= set(schedule["daily-finreports-reconcile"]["schedule"].hour)

    assert {0, 1, 2, 4} <= hours


def test_the_days_a_weekly_report_is_formed_are_asked_every_quarter_hour() -> None:
    """Monday and the first of the month, through the whole observed window.

    A weekly report is created the day after its period closes — a Sunday or a
    month end, 142 of 142 — and has been served between 10:03 and 18:30.
    """
    schedule = celery_app.conf.beat_schedule
    monday = schedule["finreports-harvest-after-a-sunday"]["schedule"]
    first = schedule["finreports-harvest-after-a-month-end"]["schedule"]
    by_day = schedule["finreports-harvest-by-day"]["schedule"]

    assert monday.day_of_week == {1}
    assert first.day_of_month == {1}
    for entry in (monday, first):
        assert set(entry.hour) >= set(range(10, 19))
        assert len(entry.minute | by_day.minute) == 4


def test_the_finance_harvest_leaves_the_monitoring_hours_alone() -> None:

    The finance tick competes with them for the same rate-limited analytics
    surfaces whenever it has a report to walk, so it is the one that yields.
    """
    schedule = celery_app.conf.beat_schedule
    hours: set[int] = set()
    for entry in _finance_ticks().values():
        hours |= set(entry["schedule"].hour)
    reserved = {
        min(schedule["daily-finreports-snapshot-tariffs"]["schedule"].hour),
        min(schedule["nightly-harvest-all"]["schedule"].hour),
        min(schedule["daily-finreports-reconcile"]["schedule"].hour),
    }

    assert hours & reserved == set()


def test_results_expire_so_redis_does_not_grow_without_bound() -> None:
    """Every enqueued refresh leaves a result key; unbounded they fill Redis.

    Redis is also the broker — filling it stops the queue, not just the cache.
    """
    assert celery_app.conf.result_expires


def test_late_acknowledgement_is_enabled() -> None:
    """A worker killed mid-harvest must not silently lose the task.

    ``task_acks_late`` re-queues the job instead of acknowledging it up front,
    which is what makes a redeploy during a harvest safe.
    """
    assert celery_app.conf.task_acks_late is True


def test_only_json_payloads_are_accepted() -> None:
    """Pickle over a network broker is remote code execution.

    Redis carries these payloads; accepting pickle would turn any broker access
    into arbitrary code running in the worker.
    """
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.task_serializer == "json"


def test_the_refresh_route_enqueues_the_task_it_names() -> None:
    """The API's per-SKU refresh points at a task that exists.

    The router calls ``harvest_sku_window.delay(...)``; if that import ever
    drifted from the registered name, the endpoint would accept the request,
    return 202, and nothing would ever run.
    """
    from src.modules.monitoring.tasks import harvest_sku_window

    assert harvest_sku_window.name == "monitoring.harvest_sku_window"
    # Compared by name, not identity: Celery hands out proxy objects, so the
    # registry entry and the imported symbol are equal but never the same object.
    assert celery_app.tasks[harvest_sku_window.name].name == harvest_sku_window.name


def test_scheduled_entries_use_real_crontabs() -> None:
    """Every entry carries a schedule object beat can actually evaluate."""
    for name, entry in celery_app.conf.beat_schedule.items():
        assert isinstance(entry["schedule"], crontab), f"{name} has no crontab schedule"
