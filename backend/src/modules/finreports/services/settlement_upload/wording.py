"""What the seller is told about an upload — short, and in their words."""

from __future__ import annotations

from datetime import date

from src.core.calendar_words import period_text


def rows_text(count: int) -> str:
    """Return a row count as "3,257 rows" or "1 row"."""
    return f"{count:,} {'row' if count == 1 else 'rows'}"


def written(date_from: date, date_to: date, *, total: int, added: int) -> str:
    """The rows now stand in the P&L — all of the file, or the ones we lacked."""
    period = period_text(date_from, date_to)
    if added == total:
        return (
            f"Report for {period} uploaded: {rows_text(total)}. "
            "We'll check it against WB once the API serves it."
        )
    return (
        f"Report for {period} uploaded: {rows_text(added)} added, the rest we already had. "
        "We'll check it against WB once the API serves it."
    )


ALREADY_HELD = "We already have this report, and it matches the file row for row."
DIVERGED = "We already have this report, but it differs from the file. We'll look into it."
EMPTY = "The report has no rows."
NO_CURRENCY = "Wait for WB's first report: it tells us the settlement currency."
FAILED = "Couldn't process the file. Try uploading it again."


def not_over(date_from: date, date_to: date) -> str:
    """The week is still running, so WB has no report for it yet."""
    return f"The week of {period_text(date_from, date_to)} isn't over yet, so there is no report."


__all__ = [
    "ALREADY_HELD",
    "DIVERGED",
    "EMPTY",
    "FAILED",
    "NO_CURRENCY",
    "not_over",
    "rows_text",
    "written",
]
