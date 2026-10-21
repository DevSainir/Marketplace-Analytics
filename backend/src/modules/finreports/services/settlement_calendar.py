"""Which weekly settlement period a day belongs to — WB's calendar, derived.

A period ends on **a Sunday or on the last day of the month, whichever comes
first**, and the next one starts the day after; WB forms its report the day
after the period ends (``create_dt = date_to + 1``). Measured over all 142
reports «Демо» held on 2026-09-19 and every one since, with no exception: the
publication calendar is derivable.

The month-end half started on 2026-03-30; before that WB ran plain Sunday weeks
through month boundaries. So this predicts forward and does not describe older
history: on an old day it can only answer with a period that ends EARLIER than
WB's did, never later.

Formed is not served. The report exists on WB's site from the morning after the
period, and the API has served it anywhere from the same hour to eight days
later (983241109). Nothing here says a report can be fetched — only that WB has
made one.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

_SUNDAY = 6


def settlement_period_end(day: date) -> date:
    """Last day of the weekly settlement period that contains ``day``."""
    sunday = day + timedelta(days=_SUNDAY - day.weekday())
    month_end = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return min(sunday, month_end)


def settlement_period_start(day: date) -> date:
    """First day of the weekly settlement period that contains ``day``."""
    monday = day - timedelta(days=day.weekday())
    return max(monday, day.replace(day=1))


def last_due_settlement_day(*, today: date, grace_days: int) -> date:
    """Newest day whose weekly report should be in hand by ``today``.

    A day is due once its whole PERIOD has been over for ``grace_days`` — not
    once the day itself has. Every day of a week is settled by one report formed
    the day after the Sunday, so counting the grace from the day made the
    Monday of every week «uncovered» on the following Monday morning, hours
    before WB serves the report that covers it (observed 05.10 and 12.10.2026).

    Args:
        today: Today in Moscow time.
        grace_days: How long after a period ends WB may stay silent before the
            silence is ours to explain.

    Returns:
        The end of the newest period that ended at least ``grace_days`` ago.
    """
    cutoff = today - timedelta(days=grace_days)
    if settlement_period_end(cutoff) == cutoff:
        return cutoff
    return settlement_period_start(cutoff) - timedelta(days=1)


def next_formed_period(*, after: date, today: date) -> tuple[date, date] | None:
    """The period right after ``after``, if WB has formed its report by ``today``.

    Args:
        after: Last day of the newest period we hold.
        today: Today in Moscow time.

    Returns:
        ``(date_from, date_to)`` of the next period when it ended before
        today — WB forms the report the morning after — or ``None`` while it is
        still running.
    """
    start = after + timedelta(days=1)
    end = settlement_period_end(start)
    return (start, end) if end < today else None


__all__ = [
    "last_due_settlement_day",
    "next_formed_period",
    "settlement_period_end",
    "settlement_period_start",
]
