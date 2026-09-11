"""The watchdog, and the invariant whose violation created the need for it.

A backfill lane is a chain of self-enqueueing ticks with exactly one thread of
continuation. On 2026-09-10 NEVA's P&L lane broke that thread on its first tick
and nothing noticed for eleven hours. These are the two guards against a repeat:
the restart path must be wired to real tasks, and a tick must never be able to
block for longer than it is allowed to live.
"""

from __future__ import annotations

from datetime import timedelta

from src.core.celery_app import celery_app
from src.core.config import settings
from src.modules.finreports.tasks.backfill import (
    _NEXT_PAGE_SECONDS,
    _TICK_SOFT_LIMIT_SECONDS,
)
from src.modules.workspaces.models import BackfillLane
from src.modules.workspaces.tasks import LANE_TASKS, STALE_AFTER


def test_a_tick_cannot_block_for_longer_than_it_is_allowed_to_live() -> None:
    """The exact bug that killed NEVA's P&L lane, as an assertion.

    The lane was wired to the rate gate that QUEUES rather than the one that
    refuses. Asked at 18:00:04 it answered "waiting 956.0s for a rate token";
    Celery's 300 s soft limit killed the task five minutes later, and
    ``SoftTimeLimitExceeded`` is not the ``IntegrationError`` the lane catches —
    so nothing was recorded and nothing re-enqueued.

    The rule that prevents it: whatever gate a tick waits on must give up well
    inside the tick's own lifetime, so a shut window comes back as a refusal the
    lane can handle rather than as a killed worker.
    """
    assert settings.wb_statistics_max_queue_seconds < _TICK_SOFT_LIMIT_SECONDS


def test_the_next_page_is_scheduled_beyond_wb_s_own_window() -> None:
    """Asking sooner than WB reopens restarts its block and costs the next one.

    So the re-enqueue delay is not a tuning knob — anything under the endpoint's
    ~15-minute budget makes the lane slower rather than faster.
    """
    assert _NEXT_PAGE_SECONDS >= 15 * 60


def test_every_lane_has_a_restart_task_that_actually_exists() -> None:
    """The watchdog addresses tasks by name, which no type checker can follow.

    A rename that skipped this table would leave the sweep enqueueing a task no
    worker answers — silently disabling the one thing that catches a dead lane.
    """
    import src.modules.finreports.tasks
    import src.modules.monitoring.tasks  # noqa: F401

    for lane in BackfillLane:
        assert lane in LANE_TASKS, f"lane {lane} has no restart task"
        assert LANE_TASKS[lane] in celery_app.tasks


def test_the_watchdog_is_patient_enough_for_the_slowest_lane() -> None:
    """A healthy slow lane must never be restarted out from under itself.

    The P&L tick moves once per ~15.5 minutes, and a tick that finds WB's window
    shut legitimately records nothing but a message. The staleness threshold has
    to clear several of those, or the sweep would keep enqueueing duplicates of
    a lane that is working exactly as designed.
    """
    assert timedelta(seconds=_NEXT_PAGE_SECONDS * 2) <= STALE_AFTER


def test_the_watchdog_is_registered_on_the_beat_schedule() -> None:
    """A watchdog nothing runs is worse than none: it reads as covered."""
    entries = celery_app.conf.beat_schedule.values()
    assert any(entry["task"] == "workspaces.sweep_stalled_backfills" for entry in entries)
