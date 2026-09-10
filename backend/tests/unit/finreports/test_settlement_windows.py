"""One week per request, and where the week starts.

WB serves `reportDetailByPeriod` once per quarter of an hour per seller token
(`x-ratelimit-limit: 1`, `x-ratelimit-reset: 917`, measured 2026-09-07), and a
request made inside that window restarts it. Two design choices follow, and
both are the kind that would keep working for months on a small seller before
failing on a large one:

* the span is walked a **week** at a time, so a request covers a whole WB
  report rather than a page of an arbitrary 28-day window;
* the span **starts at the last settled day**, not 28 days back, because
  re-reading a month costs four quarter-hours of a harvest that runs hourly.

The wait between weeks is asserted where it matters — that it happens with no
transaction open — in `tests/integration/finreports/test_harvest_is_atomic.py`.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.modules.finreports.tasks.settlement import settlement_windows
from src.modules.finreports.tasks.spans import walk_span

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 7)


# --- settlement_windows ---------------------------------------------------


def test_a_month_is_walked_as_whole_weeks_oldest_first() -> None:
    """Four requests, not one paged walk — and the oldest week goes first.

    Order matters on a backfill that runs out of budget part-way: covering the
    early weeks leaves the gap adjacent to today, which is exactly where the
    next run's span begins. Covering the recent ones first would leave a hole
    behind the last settled day that nothing would ever go back for.
    """
    windows = settlement_windows(date_from=date(2026, 8, 10), date_to=date(2026, 9, 6))

    assert windows == [
        (date(2026, 8, 10), date(2026, 8, 16)),
        (date(2026, 8, 17), date(2026, 8, 23)),
        (date(2026, 8, 24), date(2026, 8, 30)),
        (date(2026, 8, 31), date(2026, 9, 6)),
    ]


def test_the_windows_are_contiguous_and_cover_every_day_once() -> None:
    """A day in two windows is a row upserted twice; a day in none is missing money."""
    windows = settlement_windows(date_from=date(2026, 8, 12), date_to=date(2026, 9, 6))

    covered = [day for start, end in windows for day in _days(start, end)]

    assert covered == _days(date(2026, 8, 12), date(2026, 9, 6))


def test_a_short_span_is_one_window() -> None:
    """A single new report must not cost more than the one request it needs."""
    assert settlement_windows(date_from=date(2026, 9, 1), date_to=date(2026, 9, 6)) == [
        (date(2026, 9, 1), date(2026, 9, 6))
    ]


def test_an_inverted_span_asks_for_nothing() -> None:
    """ "Everything is already covered" must cost zero requests, not one empty one.

    Under a one-request-per-quarter-hour budget an empty ask is not free: it
    spends the token the next real window needs.
    """
    assert settlement_windows(date_from=date(2026, 9, 7), date_to=date(2026, 9, 6)) == []


# --- walk_span -----------------------------------------------------------


def test_a_never_harvested_workspace_backfills_the_full_window() -> None:
    """The one case that legitimately costs several quarter-hours."""
    span = walk_span(latest_settled=None, today=TODAY, days=28)

    assert span == (date(2026, 8, 9), date(2026, 9, 6))


def test_a_harvested_workspace_starts_at_its_own_last_settled_day() -> None:
    """Including that day, so WB's amendments to the newest report land.

    Starting the day AFTER would never re-read a report we already hold, and
    WB restates them; starting 28 days back would re-read three reports that
    have not changed, at a quarter of an hour each.
    """
    span = walk_span(latest_settled=date(2026, 8, 30), today=TODAY, days=28)

    assert span == (date(2026, 8, 30), date(2026, 9, 6))
    assert len(settlement_windows(date_from=span[0], date_to=span[1])) == 2


def test_a_long_absent_workspace_is_still_capped_at_the_window() -> None:
    """A workspace harvested a year ago must not walk a year of quarter-hours."""
    span = walk_span(latest_settled=date(2025, 9, 1), today=TODAY, days=28)

    assert span == (date(2026, 8, 9), date(2026, 9, 6))


def test_a_workspace_settled_through_yesterday_asks_for_one_window() -> None:
    """Its own last day is re-read; nothing beyond it exists yet."""
    span = walk_span(latest_settled=date(2026, 9, 6), today=TODAY, days=28)

    assert span == (date(2026, 9, 6), date(2026, 9, 6))


def _days(start: date, end: date) -> list[date]:
    """Every day in an inclusive span."""
    from datetime import timedelta

    out = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out
