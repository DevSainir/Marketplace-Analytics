"""What the profile's lane percentages are allowed to say.

``total_units`` is an estimate every lane may revise, and two of the four
routinely finish below it: the funnel stops at the seller's first trade, and
advertising stops when every campaign is covered. So the ratio cannot be what
decides "finished", and a finished lane cannot be allowed to render at 40%
while the words beside it say «готово».
"""

from __future__ import annotations

from src.modules.workspaces.backfill import LANE_LABELS, LANE_ORDER, LaneStep, _percent
from src.modules.workspaces.models import BackfillState, WorkspaceBackfill


def _row(*, state: str, done: int, total: int) -> WorkspaceBackfill:
    """A lane row with just the fields the percentage reads."""
    return WorkspaceBackfill(state=state, done_units=done, total_units=total)


def test_a_finished_lane_reads_100_even_when_it_stopped_early() -> None:
    """The normal ending for a young account, and it must not look broken.

    A shop that opened in June has ~80 days of funnel, not 365. The walk ends
    correctly and the counters honestly say 80/365 — but the lane is done, and
    a bar frozen at 22% next to «готово» reads as a stuck job.
    """
    assert _percent(_row(state=BackfillState.DONE, done=80, total=365)) == 100


def test_a_running_lane_reads_its_real_ratio() -> None:
    """While it is running the counters are the truth, rounded."""
    assert _percent(_row(state=BackfillState.RUNNING, done=73, total=365)) == 20


def test_a_lane_that_has_not_estimated_yet_reads_zero_rather_than_dividing() -> None:
    """``total`` is 0 between seeding and the first tick — not a crash site."""
    assert _percent(_row(state=BackfillState.PENDING, done=0, total=0)) == 0


def test_a_lane_that_overshot_its_estimate_is_clamped() -> None:
    """An estimate revised downward must not produce 140% on the screen."""
    assert _percent(_row(state=BackfillState.RUNNING, done=500, total=365)) == 100


def test_every_lane_has_a_russian_label() -> None:
    """The label is rendered verbatim, so a missing one shows an enum name.

    ``read_progress`` indexes ``LANE_LABELS`` by lane; a lane added without a
    label would raise there — in a request the seller made — rather than here.
    """
    for lane in LANE_ORDER:
        assert LANE_LABELS[lane]
        assert not LANE_LABELS[lane].isascii()


def test_a_tick_that_learned_nothing_leaves_the_counter_alone() -> None:
    """A refused page must not reset the bar to zero and then jump it back.

    Observed live 2026-09-11: NEVA's second P&L tick was answered with a 429
    carrying a 48-minute penalty. The lane handled it correctly — no page, no
    cursor movement — but reported ``done=0``, which overwrote 1078 days of
    real progress. Flapping 1078 -> 0 -> 1078 reads as the walk restarting.

    ``None`` is how a step says "I advanced nothing"; the repository then
    touches only what was passed.
    """
    step = LaneStep(done=None, total=1792, cursor="x", finished=False, message="…")

    assert step.done is None
