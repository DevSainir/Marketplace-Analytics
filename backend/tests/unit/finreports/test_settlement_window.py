"""Unit tests for the finreports default settlement window.

WB dates every settlement row by the **Moscow** calendar day. The service runs
on a UTC host, so a window whose open end is filled from the server's own
``date.today()`` is one day short for the three hours between 00:00 and 03:00
MSK — quietly dropping the most recent settlement day from every total a caller
asks for without explicit dates.

These tests pin the window against the Moscow clock, and against the operating
clock too: those two disagree for a *different* three hours (21:00-24:00 MSK),
so passing one is not passing the other.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.core.timeutils import MOSCOW_TZ, moscow_today
from src.modules.finreports.routers.window import DEFAULT_WINDOW_DAYS, resolve_window


def test_the_open_end_is_the_moscow_day_not_the_hosts() -> None:
    """An omitted ``date_to`` resolves to today in Moscow, whatever TZ the host runs in."""
    start, end = resolve_window(None, None)

    assert end == moscow_today()
    assert start == end - timedelta(days=DEFAULT_WINDOW_DAYS)


def test_the_open_end_never_lags_the_moscow_calendar() -> None:
    """The resolved end is never *behind* the Moscow day.

    This is the actual failure mode of the bug: on a UTC host between 00:00 and
    03:00 MSK, ``date.today()`` is still yesterday in Moscow terms. Asserting
    ">= " rather than "==" keeps the test honest across a midnight boundary that
    could tick between the two reads.
    """
    _, end = resolve_window(None, None)

    assert end >= moscow_today() - timedelta(days=1)
    assert end <= moscow_today()


def test_an_explicit_window_is_passed_through_untouched() -> None:
    """Given both dates, the resolver is a no-op — no clock is consulted."""
    start, end = resolve_window(date(2026, 3, 1), date(2026, 3, 15))

    assert (start, end) == (date(2026, 3, 1), date(2026, 3, 15))


def test_an_explicit_end_anchors_the_default_start() -> None:
    """Only ``date_from`` missing: the look-back counts from the GIVEN end."""
    start, end = resolve_window(None, date(2026, 3, 15))

    assert end == date(2026, 3, 15)
    assert start == date(2026, 3, 15) - timedelta(days=DEFAULT_WINDOW_DAYS)


def test_the_window_covers_four_whole_weeks() -> None:
    """The default span is 28 days — four WB realization weeks, not "about a month"."""
    start, end = resolve_window(None, None)

    assert (end - start).days == 28
    assert (end - start).days % 7 == 0


def test_the_resolver_uses_the_same_timezone_object_as_the_harvest() -> None:
    """The window and the harvest must agree on which day "today" is.

    The harvest counts its days with ``moscow_today()``; a window resolved
    against any other zone could ask for a day the harvest has not reached.
    """
    assert str(MOSCOW_TZ) == "Europe/Moscow"
    assert resolve_window(None, None)[1] == moscow_today()
