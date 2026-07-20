"""Shared time helpers for WB-aligned business dates.

WildBerries operates strictly in Moscow time (UTC+3): every funnel/advertising
row is dated by the Moscow calendar day. Any code that derives "today" for
windowing or snapshots MUST use these helpers — ``date.today()`` on a UTC
server disagrees with the data's dating between 00:00 and 03:00 MSK.

Two clocks meet here, and they answer different questions:

* :func:`moscow_today` — how WB dates its DATA. Use it for windows, snapshots,
  and anything compared against harvested rows.
* :func:`operating_today` — when the TEAM's day turns over (Bishkek, UTC+6, so
  00:00 there is 21:00 MSK). Use it for day-boundary work the managers
  experience as "a new day started", such as carrying note headers forward.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

#: WB operates strictly in Moscow Time (UTC+3).
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

#: The team's own clock (UTC+6). Their day begins at 00:00 Bishkek = 21:00 MSK,
#: three hours before the Moscow calendar day rolls over.
OPERATING_TZ = ZoneInfo("Asia/Bishkek")


def moscow_today() -> date:
    """Return the current calendar date in Moscow time (UTC+3)."""
    return datetime.now(tz=MOSCOW_TZ).date()


def operating_today(now: datetime | None = None) -> date:
    """Return the current date on the team's operating clock (Bishkek, UTC+6).

    This is the date whose column the managers consider "today": it advances at
    21:00 MSK, so between 21:00 and 24:00 MSK it is already one day ahead of
    :func:`moscow_today`.

    Args:
        now: Instant to read (any timezone); defaults to the current time.

    Returns:
        The calendar date at ``now`` in the operating timezone.
    """
    moment = now or datetime.now(tz=OPERATING_TZ)
    return moment.astimezone(OPERATING_TZ).date()
