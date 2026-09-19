"""When WB forms a settlement report, derived rather than discovered.

The hourly probe existed because the answer to «is there a new report» was
believed to be unknowable: the module it guards still says WB publishes «on no
fixed day and no fixed hour». The first half of that is wrong, and this module
is what replaces it.

**Measured over all 142 reports «Демо» holds, 2024-01-29 to 2026-09-13:**

* ``create_dt`` is ``date_to + 1``. One hundred and forty-two times out of one
  hundred and forty-two, with no exception in two and a half years.
* A settlement period ends on **a Sunday or on the last day of the month,
  whichever comes first**, and the next period starts the day after. Over the
  29 periods since 2026-03-30 the rule reproduces every boundary exactly,
  including all seven short periods — 1, 2, 2, 3, 4, 5 and 5 days — which were
  month splits rather than anomalies.

The month-end half of the rule STARTED on 2026-03-30. Before that WB ran plain
seven-day Sunday weeks straight through month boundaries, so the periods this
module derives do not describe the older history and are not meant to: it
predicts forward, and forward the rule has held for six months.

What is NOT predictable is the hour, and more importantly whether WB serves the
report on the day it formed it at all. Report 983241109 (31.08 alone) was
formed on 01.09 and first answered on 09.09 — eight days. So the date this
module derives is the earliest a report CAN exist, never a promise that it
does, and :func:`missing_periods` is written to keep asking about a period
until the report for it is actually held rather than until the calendar moves
on. That last part is the hole the forward-only walk had: on 2026-08-31 the
watermark jumped over 31.08 to 06.09 and the day became unreachable.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta

#: The last weekday of a settlement period. ``date.weekday()`` numbers Monday
#: 0, so Sunday is 6.
_SUNDAY = 6


@dataclass(frozen=True, slots=True)
class Period:
    """One WB settlement period and the day WB stamps on its report.

    Attributes:
        date_from: First settlement day, inclusive.
        date_to: Last settlement day, inclusive.
        created_on: The ``create_dt`` WB will stamp — always ``date_to + 1``,
            and the earliest day the report can be served.
    """

    date_from: date
    date_to: date
    created_on: date


def period_from(start: date) -> Period:
    """The settlement period that begins on ``start``.

    Args:
        start: The period's first day. WB chains periods, so this is the day
            after the previous period's ``date_to``.

    Returns:
        The period, ending at the earlier of the next Sunday and the month's
        last day.
    """
    sunday = start + timedelta(days=(_SUNDAY - start.weekday()) % 7)
    last_of_month = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    end = min(sunday, last_of_month)
    return Period(date_from=start, date_to=end, created_on=end + timedelta(days=1))


def periods_from(start: date, *, through: date) -> Iterator[Period]:
    """Every settlement period beginning at ``start`` and formed by ``through``.

    Yields only periods WB has already stamped — a period whose ``created_on``
    is after ``through`` cannot be served yet, so asking about it spends a
    request on a certainty.

    Args:
        start: First settlement day not yet covered by a held report.
        through: Today, in Moscow time. Nothing formed later is yielded.

    Yields:
        Periods in chronological order, ending before the first one WB has not
        formed yet.
    """
    cursor = start
    while True:
        period = period_from(cursor)
        if period.created_on > through:
            return
        yield period
        cursor = period.date_to + timedelta(days=1)


def missing_periods(
    *, settled_through: date, held_ends: Iterable[date], today: date
) -> list[Period]:
    """Every period WB has formed that we do not hold a report for.

    The question the hourly probe was asking WB twenty-one times a day, asked
    of our own database instead. It costs one indexed read and no WB request,
    and it is strictly better informed: the probe could only see forward from
    the watermark, while this compares the full set of periods WB must have
    formed against the full set we hold.

    That difference is the 31.08.2026 hole. The probe's window began at the
    watermark, the watermark jumped to 06.09 when the 01.09-06.09 report landed
    first, and 31.08 was behind it for ever. Here 31.08 is simply a period
    whose report is absent, and it stays in this list until it is not.

    Args:
        settled_through: Last day covered by a report we hold contiguously from
            the beginning of history — where the chain of periods resumes.
        held_ends: ``date_to`` of every report already held. Only membership is
            read, so any iterable of dates will do.
        today: Today in Moscow time.

    Returns:
        The missing periods, oldest first. Empty when the history is complete
        up to the last period WB has formed — which is the state that lets a
        tick skip without asking WB anything.
    """
    held = set(held_ends)
    start = settled_through + timedelta(days=1)
    return [p for p in periods_from(start, through=today) if p.date_to not in held]


__all__ = ["Period", "missing_periods", "period_from", "periods_from"]
