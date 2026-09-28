"""The heatmap's columns: calendar weeks and months, clipped to the window, newest first."""

from __future__ import annotations

from datetime import date

from src.modules.heatmap.services.periods import build_columns, column_of_day


def test_days_run_newest_first() -> None:
    """The grid reads from yesterday backwards, the way a seller scans it."""
    columns = build_columns(date(2026, 9, 17), date(2026, 9, 19), "day")

    assert [start for start, _ in columns] == [
        date(2026, 9, 19),
        date(2026, 9, 18),
        date(2026, 9, 17),
    ]


def test_weeks_are_monday_to_sunday_and_clipped_to_the_window() -> None:
    """A window from a Wednesday opens with a short week, not a Wednesday-to-Tuesday one."""
    columns = build_columns(date(2026, 9, 16), date(2026, 9, 29), "week")

    assert columns == [
        (date(2026, 9, 28), date(2026, 9, 29)),
        (date(2026, 9, 21), date(2026, 9, 27)),
        (date(2026, 9, 16), date(2026, 9, 20)),
    ]


def test_months_start_on_the_first() -> None:
    """A month column ends on its last calendar day, whatever its length."""
    columns = build_columns(date(2026, 1, 20), date(2026, 3, 5), "month")

    assert columns == [
        (date(2026, 3, 1), date(2026, 3, 5)),
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 1, 20), date(2026, 1, 31)),
    ]


def test_every_day_of_the_window_lands_in_exactly_one_column() -> None:
    """No day is dropped at a week boundary and none is counted twice."""
    columns = build_columns(date(2026, 9, 16), date(2026, 9, 29), "week")

    index = column_of_day(columns)

    assert len(index) == 14
    assert index[date(2026, 9, 20)] == 2
    assert index[date(2026, 9, 21)] == 1
