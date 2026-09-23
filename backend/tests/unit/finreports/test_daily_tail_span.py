"""Which days the provisional daily tail is allowed to reach for.

The tail exists to cover the gap between the last settled week and yesterday,
and every failure mode of it is a span mistake:

* reaching into days the weekly lane has already settled would re-fetch rows the
  settlement document owns, at one WB request a minute, and flip their
  ``report_id`` to a provisional one for no gain;
* reaching for today would ask WB for data that does not exist anywhere on the
  platform — the daily list asked on 23.09 does not contain 23.09;
* reaching back without a floor would turn a workspace stuck months behind into a
  hundred daily reports at one request a minute, behind a lock the whole fleet
  shares.

So the span rule is pinned here rather than left to the caller.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.modules.finreports.constants import DAILY_TAIL_LOOKBACK_DAYS
from src.modules.finreports.tasks.daily_tail import _tail_span

pytestmark = pytest.mark.unit

#: A Wednesday, so «yesterday» is an ordinary trading day rather than a boundary.
TODAY = date(2026, 9, 23)
YESTERDAY = date(2026, 9, 22)


def test_the_tail_starts_after_the_settled_frontier() -> None:
    """A settled day is the weekly lane's; the tail begins the day after."""
    span = _tail_span(frontier=date(2026, 9, 20), today=TODAY)

    assert span == (date(2026, 9, 21), YESTERDAY)


def test_the_tail_stops_at_yesterday() -> None:
    """Today is never asked for — WB has no data for it on any surface."""
    span = _tail_span(frontier=date(2026, 9, 15), today=TODAY)

    assert span is not None
    assert span[1] == YESTERDAY


def test_a_settled_history_that_already_reaches_yesterday_has_no_tail() -> None:
    """The ordinary Monday state, and not a problem: there is nothing to add."""
    assert _tail_span(frontier=YESTERDAY, today=TODAY) is None


def test_a_settled_history_ahead_of_yesterday_has_no_tail() -> None:
    """WB can stamp a period ending today; the tail must not run backwards."""
    assert _tail_span(frontier=TODAY, today=TODAY) is None


def test_a_workspace_months_behind_is_clamped_to_the_lookback() -> None:
    """A stuck weekly lane must not become a hundred requests a tick."""
    span = _tail_span(frontier=date(2026, 5, 1), today=TODAY)

    assert span == (TODAY - timedelta(days=DAILY_TAIL_LOOKBACK_DAYS), YESTERDAY)


def test_a_never_settled_workspace_starts_at_the_lookback_floor() -> None:
    """No frontier is not licence to walk the whole history one day at a time.

    A new workspace's history is the backfill's job, on the weekly lane where a
    request covers a week rather than a day.
    """
    span = _tail_span(frontier=None, today=TODAY)

    assert span == (TODAY - timedelta(days=DAILY_TAIL_LOOKBACK_DAYS), YESTERDAY)
