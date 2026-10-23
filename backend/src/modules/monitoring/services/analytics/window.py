"""Resolution and validation of the shared analysis date window."""

from __future__ import annotations

from datetime import date, timedelta

from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today
from src.modules.monitoring.constants import MAX_WINDOW_DAYS

#: Default look-back window (days) when the caller omits explicit dates.
_DEFAULT_WINDOW_DAYS = 30

#: Hard ceiling on a requested window. Shared with the request schemas through
#: the module's constants, so the days a caller may ASK for and the days a
#: caller may ASSERT in a matrix body cannot drift apart.
_MAX_WINDOW_DAYS = MAX_WINDOW_DAYS


def resolve_window(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Resolve an inclusive analysis window, applying defaults and validation.

    Application logic (not presentation): the router passes the raw optional
    query params straight through and this decides the effective window.

    Args:
        date_from: Optional inclusive start; defaults to ``date_to`` minus the
            default look-back window.
        date_to: Optional inclusive end; defaults to today in Moscow time —
            WB data is dated by the Moscow calendar day, so a UTC server's
            ``date.today()`` would misalign the window between 00:00-03:00 MSK.

    Returns:
        A validated ``(start, end)`` tuple.

    Raises:
        ValidationError: If the resolved start is after the end, or the window
            exceeds :data:`_MAX_WINDOW_DAYS`.
    """
    end = date_to or moscow_today()
    start = date_from or (end - timedelta(days=_DEFAULT_WINDOW_DAYS))
    if start > end:
        raise ValidationError("The start date is after the end date.")
    if (end - start).days > _MAX_WINDOW_DAYS:
        raise ValidationError(f"The period cannot exceed {_MAX_WINDOW_DAYS} days.")
    return start, end
