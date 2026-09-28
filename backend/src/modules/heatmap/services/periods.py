"""The heatmap's columns: the window cut into days, calendar weeks or calendar months.

Weeks run Monday to Sunday and months from the 1st, as a seller counts them —
not seven-day slices from the window's start, which would put a Wednesday at
the head of every «неделя». The first and last column are clipped to the
window, so a partial week says so in its own dates rather than silently
reporting three days as seven.

Newest first: the grid reads from today backwards, the way the reference
screen does and the way a seller scans for «что случилось вчера».
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.heatmap.schemas import Period


def _bucket_start(day: date, period: Period) -> date:
    """The first day of the calendar bucket ``day`` falls in."""
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    return day


def _next_bucket(start: date, period: Period) -> date:
    """The first day of the bucket after the one starting on ``start``."""
    if period == "week":
        return start + timedelta(days=7)
    if period == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=1)


def build_columns(date_from: date, date_to: date, period: Period) -> list[tuple[date, date]]:
    """Cut ``[date_from, date_to]`` into ``(start, end)`` columns, newest first.

    Args:
        date_from: Inclusive window start.
        date_to: Inclusive window end, not before ``date_from``.
        period: Day, calendar week or calendar month.
    """
    columns: list[tuple[date, date]] = []
    start = _bucket_start(date_from, period)
    while start <= date_to:
        following = _next_bucket(start, period)
        columns.append((max(start, date_from), min(following - timedelta(days=1), date_to)))
        start = following
    columns.reverse()
    return columns


def column_of_day(columns: list[tuple[date, date]]) -> dict[date, int]:
    """Map every day of the window to the index of the column that holds it."""
    index: dict[date, int] = {}
    for position, (start, end) in enumerate(columns):
        day = start
        while day <= end:
            index[day] = position
            day += timedelta(days=1)
    return index
