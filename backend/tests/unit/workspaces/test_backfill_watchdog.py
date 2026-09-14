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

    The P&L lane paces itself against WB and widens whenever a page is refused,
    so "slow" here is not a constant — the patience has to clear the slowest
    interval the lane is ALLOWED to reach, not the one it starts at.
    """
    from src.modules.finreports.tasks.backfill.pace import PACE_CEILING_SECONDS
    from src.modules.workspaces.tasks import _patience

    assert timedelta(seconds=PACE_CEILING_SECONDS) < _patience(BackfillLane.PNL)
    assert timedelta(seconds=_NEXT_PAGE_SECONDS * 2) <= _patience(BackfillLane.PNL)


def test_the_pace_cannot_be_capped_by_the_watchdog_it_should_outlive() -> None:
    """The bug this pairing exists to prevent, stated as the relationship.

    With patience fixed at 45 minutes the pace ceiling had to sit below it, so
    the walk pinned against a cap it kept trying to cross — NEVA served four
    pages against six refusals in six hours, spending roughly 40% of the
    endpoint's budget on requests WB was always going to reject. Raising one
    without the other silently restores that.
    """
    from src.modules.finreports.tasks.backfill.pace import (
        PACE_CEILING_SECONDS,
        PACE_DEFAULT_SECONDS,
        PACE_FLOOR_SECONDS,
    )
    from src.modules.workspaces.tasks import _patience

    assert PACE_FLOOR_SECONDS < PACE_DEFAULT_SECONDS < PACE_CEILING_SECONDS
    assert _patience(BackfillLane.PNL) >= timedelta(seconds=PACE_CEILING_SECONDS * 2)


def test_the_fast_lanes_keep_the_short_leash() -> None:
    """Raising one lane's patience must not blunt the watchdog everywhere.

    The three monitoring lanes tick every few seconds; giving them the
    settlement lane's three hours would turn a dead catalogue into an afternoon
    of a new seller staring at an empty profile.
    """
    from src.modules.workspaces.tasks import _patience

    for lane in (BackfillLane.CATALOGUE, BackfillLane.FUNNEL, BackfillLane.ADVERTISING):
        assert _patience(lane) == STALE_AFTER


def test_the_watchdog_is_registered_on_the_beat_schedule() -> None:
    """A watchdog nothing runs is worse than none: it reads as covered."""
    entries = celery_app.conf.beat_schedule.values()
    assert any(entry["task"] == "workspaces.sweep_stalled_backfills" for entry in entries)


def test_no_lane_can_spend_more_than_its_tick_on_rate_gates() -> None:
    """The failure that killed two different lanes, as arithmetic.

    A tick does one bounded unit and each WB call waits ~20 s at the shared
    gate, so the ceiling is (calls per tick x gate wait) and it must clear the
    soft time limit with room. The advertising lane broke this by sending one
    WINDOW per tick: `fetch_full_stats` batches ids at 50, so an account with
    ~360 campaigns spent eight gated calls — 160 s of pure waiting — and was
    killed mid-window, ending the chain. It sends one BATCH per tick now.
    """
    from src.modules.monitoring.services.backfill import (
        ADV_BATCH,
        CALL_PAUSE_SECONDS,
        FUNNEL_DAYS_PER_TICK,
    )

    # Advertising: exactly one WB request per tick, whatever the campaign count.
    assert ADV_BATCH == 50, "one tick must equal one fullstats request"

    # Funnel: a handful of days, each one call.
    funnel_worst_case = FUNNEL_DAYS_PER_TICK * CALL_PAUSE_SECONDS
    assert funnel_worst_case < _TICK_SOFT_LIMIT_SECONDS / 2, (
        f"the funnel tick can spend {funnel_worst_case}s of a "
        f"{_TICK_SOFT_LIMIT_SECONDS}s budget before doing any work"
    )


def test_a_worker_restart_adopts_its_predecessor_s_orphaned_lanes() -> None:
    """A deploy must not cost a seller forty-five minutes of stopped history.

    Every lane is a chain of ticks, and recreating the worker kills whichever
    tick was in flight before it reaches its re-enqueue — so shipping ends the
    chain, every time. The watchdog alone would rediscover that only after
    STALE_AFTER, which turns three deploys in a morning into two hours of a
    seller's history not arriving.

    A worker that has just started is running nothing, so a lane still claiming
    RUNNING is an orphan by definition rather than a guess about staleness.
    """
    from celery.signals import worker_ready

    from src.core.celery_app import _resume_orphaned_backfills

    receivers = [receiver() for _, receiver in worker_ready.receivers]

    assert _resume_orphaned_backfills in receivers, (
        "nothing resumes a backfill after a worker restart"
    )


def test_the_orphan_sweep_asks_for_the_lanes_a_restart_stranded() -> None:
    """The hook must send `orphaned=True`, or it is just the ordinary sweep.

    An ordinary sweep at worker start finds nothing: the lanes it should be
    adopting were ticking seconds ago, so none of them looks stale yet.
    """
    import inspect

    from src.core.celery_app import _resume_orphaned_backfills

    source = inspect.getsource(_resume_orphaned_backfills)

    assert '"workspaces.sweep_stalled_backfills"' in source
    assert '"orphaned": True' in source


def test_the_sweep_restarts_a_lane_without_inheriting_its_chain() -> None:
    """A restart must SUPERSEDE the chain it replaces, not join it.

    The sweep cannot tell a dead lane from a slow one. Passing the old token
    through would make it join whatever it was wrong about, which is how NEVA ran
    two P&L chains at once — each taking half of an endpoint WB serves four
    times an hour, and each eventually declaring the lane finished.

    Sending no token is what claims the lane, so this asserts on the absence.
    """
    import inspect

    from src.modules.workspaces.tasks import sweep_stalled_backfills

    source = inspect.getsource(sweep_stalled_backfills)

    assert "send_task(" in source, "the sweep no longer enqueues anything"
    # The kwarg KEY, quoted — the prose above and in the docstring says "chain"
    # freely, and matching that made this assertion pass on anything.
    assert '"chain"' not in source
    assert "countdown=" in source, "the per-lane restart delay is not applied"


def test_the_settlement_lane_is_not_restarted_into_wb_s_closed_window() -> None:
    """An early ask on this endpoint costs three times what waiting costs.

    WB answers a request made inside its own block with a penalty rather than a
    refusal — NEVA drew ``429 ... demands a 2762s wait`` on 2026-09-12 from a
    tick fired 13 minutes after the previous one, because a deploy's orphan
    sweep restarted the lane the instant the worker came up.

    A restart cannot know how much of the window the tick it replaces had
    already spent, so it assumes none of it.
    """
    from src.modules.workspaces.tasks import LANE_RESTART_DELAY

    assert LANE_RESTART_DELAY[BackfillLane.PNL] >= _NEXT_PAGE_SECONDS


def test_the_fast_lanes_are_still_restarted_at_once() -> None:
    """The delay is a property of one endpoint, not a new default.

    The other three are paced by a bucket that refuses locally, so an early tick
    is answered by their own gate at no cost — and making a seller wait a
    quarter of an hour to resume a catalogue load would be paying the settlement
    endpoint's price on lanes that do not owe it.
    """
    from src.modules.workspaces.tasks import LANE_RESTART_DELAY

    for lane in (BackfillLane.CATALOGUE, BackfillLane.FUNNEL, BackfillLane.ADVERTISING):
        assert LANE_RESTART_DELAY.get(lane, 0) == 0
