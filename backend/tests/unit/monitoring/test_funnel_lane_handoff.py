"""Which days the funnel backfill lane may leave to the nightly cohort pass.

On 2026-09-29 the lane ran with yesterday = 28.09 and left 07.09 .. 28.09 to the
pass. The next pass ran on 30.09 and read 22 days back from ITS yesterday,
29.09 — 08.09 .. 29.09. 07.09 was read by neither, and its WB order sums stayed
missing until somebody looked.
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.services.backfill import left_to_cohort_pass
from src.modules.monitoring.tasks.cohorts import COHORT_REFRESH_DAYS


def test_the_oldest_day_of_todays_window_is_not_left_to_tomorrows_pass() -> None:
    assert left_to_cohort_pass(end=date(2026, 9, 28), day=date(2026, 9, 7)) is False


def test_a_day_tomorrows_pass_still_reads_is_left_to_it() -> None:
    assert left_to_cohort_pass(end=date(2026, 9, 28), day=date(2026, 9, 8)) is True


def test_every_day_the_lane_leaves_is_inside_the_next_pass() -> None:
    """Whatever the windows become, the lane may only hand over what the pass will read."""
    end = date(2026, 9, 28)
    next_pass_oldest = date.fromordinal(end.toordinal() + 1 - (COHORT_REFRESH_DAYS - 1))
    left = [
        date.fromordinal(end.toordinal() - offset)
        for offset in range(40)
        if left_to_cohort_pass(end=end, day=date.fromordinal(end.toordinal() - offset))
    ]
    assert min(left) >= next_pass_oldest
