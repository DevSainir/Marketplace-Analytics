"""Shared time helpers for WB-aligned business dates.

WildBerries operates strictly in Moscow time (UTC+3): every funnel/advertising
row is dated by the Moscow calendar day. Any code that derives "today" for
windowing or snapshots MUST use these helpers — ``date.today()`` on a UTC
server disagrees with the data's dating between 00:00 and 03:00 MSK.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

#: WB operates strictly in Moscow Time (UTC+3).
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def moscow_today() -> date:
    """Return the current calendar date in Moscow time (UTC+3)."""
    return datetime.now(tz=MOSCOW_TZ).date()
