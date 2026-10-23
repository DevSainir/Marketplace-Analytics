"""Unit tests for how a backend message writes a date.

A backfill lane's progress, a rejected matrix edit and a P&L note are rendered
verbatim beside the SPA's own dates, so they must read the same way: day first, the
month as a word, never an ISO string or a numeric month.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.calendar_words import day_text


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 22), "22 Oct 2026"),
        (date(2026, 1, 3), "3 Jan 2026"),
        (date(2025, 12, 31), "31 Dec 2025"),
    ],
)
def test_a_day_is_written_day_first_with_the_month_as_a_word(day: date, expected: str) -> None:
    """No zero padding, an English month whatever the process locale, the year last."""
    # Arrange / Act
    label = day_text(day)

    # Assert
    assert label == expected
