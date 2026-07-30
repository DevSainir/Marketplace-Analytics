"""Settlement-window resolution shared by every ``finreports`` route."""

from __future__ import annotations

from datetime import date, timedelta

from src.core.timeutils import moscow_today

#: Default reporting window when the caller passes no dates (last full 4 weeks).
DEFAULT_WINDOW_DAYS = 28


def resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Fill a missing settlement-date window with a sane default (last 4 weeks).

    "Today" is the MOSCOW day (:func:`~src.core.timeutils.moscow_today`), not the
    server's: WB dates every settlement row by the Moscow calendar, so on a UTC
    host ``date.today()`` resolves a window one day short between 00:00 and
    03:00 MSK — silently dropping the most recent settlement day.
    """
    end = date_to or moscow_today()
    start = date_from or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
    return start, end


__all__ = ["DEFAULT_WINDOW_DAYS", "resolve_window"]
