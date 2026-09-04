"""Every Celery task must have a deadline.

Register P0.4. The app had neither ``task_time_limit`` nor
``task_soft_time_limit``, so a task that wedged — a socket that never answers,
a walk that never converges — held its worker slot indefinitely. There are four
(``--concurrency=4``), so four such tasks are a permanently blocked queue and no
scheduled harvest runs again until a human notices.

The values are sized from production, measured over 72 h on 2026-08-29: the
longest legitimate task is ``monitoring.refresh_buyout_cohorts`` at ~1 610 s.
What these pin is not the numbers but the two properties that make them safe.
"""

from __future__ import annotations

from src.core.celery_app import celery_app
from src.modules.monitoring.tasks.refresh import harvest_sku_window


def test_every_task_has_a_deadline() -> None:
    """Both limits are configured, so no task can run forever by default."""
    conf = celery_app.conf

    assert conf.task_soft_time_limit is not None
    assert conf.task_time_limit is not None


def test_the_soft_limit_fires_before_the_hard_one() -> None:
    """Ordering is the whole design, not a detail.

    The soft limit raises inside the task, so the run unwinds and releases its
    Redis lock and DB connection. The hard limit SIGKILLs the worker, and with
    ``task_acks_late`` the message is then redelivered — a task that reliably
    overran the hard limit first would loop forever. The gap is what gives the
    soft limit room to work.
    """
    conf = celery_app.conf

    assert conf.task_soft_time_limit < conf.task_time_limit


def test_the_deadline_clears_the_longest_real_task() -> None:
    """A limit below a legitimate run would kill the nightly work every night.

    ``refresh_buyout_cohorts`` measured ~1 610 s in production; the ceiling must
    leave that room to grow as tenants are added, or this control becomes an
    outage.
    """
    longest_observed_seconds = 1610

    assert celery_app.conf.task_soft_time_limit > longest_observed_seconds * 2


def test_the_browser_triggered_harvest_is_bounded_tighter() -> None:
    """The one task a user can start on demand does not get the fleet's hour.

    It is a subset of the whole-account nightly harvest (~63 s in production),
    so the fleet-wide backstop would be a very loose bound on something anyone
    can ask for repeatedly.
    """
    interactive = harvest_sku_window.soft_time_limit

    assert interactive is not None
    assert interactive < celery_app.conf.task_soft_time_limit
