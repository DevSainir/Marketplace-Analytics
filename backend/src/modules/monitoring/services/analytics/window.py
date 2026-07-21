"""Resolution and validation of the shared analysis date window."""

from __future__ import annotations

from datetime import date, timedelta

from src.core.exceptions import ValidationError
from src.core.timeutils import moscow_today

#: Default look-back window (days) when the caller omits explicit dates.
_DEFAULT_WINDOW_DAYS = 30

#: Hard ceiling on a requested window. Bounds the work any single request can
#: demand (an unbounded `date_from=2000-01-01` was a memory/latency DoS).
_MAX_WINDOW_DAYS = 366


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
        raise ValidationError("`date_from` must not be after `date_to`.")
    if (end - start).days > _MAX_WINDOW_DAYS:
        raise ValidationError(f"The analysis window must not exceed {_MAX_WINDOW_DAYS} days.")
    return start, end
