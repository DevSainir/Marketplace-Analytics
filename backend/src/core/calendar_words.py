"""Dates as the seller reads them in a message: day first, the month as a word.

The SPA writes "22 Oct 2026" through its own formatters
(`frontend/src/core/utils/calendarWords.js`); a note, a progress line or a
rejected edit built here reaches the same screen verbatim, so it is written the
same way rather than in ISO. Month names come from this table, not ``strftime``,
whose ``%b`` follows the process locale.
"""

# ruff: noqa: RUF001, RUF002 — the en dash between two days is the typography
# the SPA prints, not a hyphen typed by mistake.
from __future__ import annotations

from datetime import date

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def day_text(day: date) -> str:
    """Return the day as "5 Oct 2026"."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def period_text(date_from: date, date_to: date) -> str:
    """Return the period as "5–11 Oct 2026" or "28 Sep – 4 Oct 2026".

    A period across New Year names both years, and a one-day report (WB forms
    them) is just its day.
    """
    if date_from == date_to:
        return day_text(date_to)
    if date_from.year != date_to.year:
        return f"{day_text(date_from)} – {day_text(date_to)}"
    if date_from.month != date_to.month:
        return f"{date_from.day} {_MONTHS[date_from.month - 1]} – {day_text(date_to)}"
    return f"{date_from.day}–{day_text(date_to)}"


__all__ = ["day_text", "period_text"]
