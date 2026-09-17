"""What a walk is handed, what it gives back, and the window arithmetic.

A fetcher is an async generator of ``(client, window) -> CaptureBatch``. It does
not touch the database, does not know which workspace it is running for and does
not decide whether to run — all three belong to :mod:`..capture`, which is what
makes a fetcher testable with a fake client and nothing else.

**It yields rather than returns, and that is the memory bound of this module.**
A fetcher used to collect every page of every window into one list and hand the
whole run over at the end, so its peak was the run: `supplier/orders` alone is
80 000 rows a page and eight pages a run, and a decoded WB order is ~2.5 KB of
Python. On 2026-09-16 the second page of a first run took the worker over its
768 MiB cgroup and the kernel killed it. Yielding moves the ceiling from "what
one run captures" to "what one batch holds", which is a constant.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

#: One captured row: WB's own identity for it, the day it is about (when the
#: feed says), and the payload verbatim.
CapturedRow = tuple[str, date | None, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CaptureWindow:
    """Everything a walk needs to know about where the last one stopped.

    Attributes:
        today: Moscow-time today. Passed in rather than read, because a walk
            that computes its own "now" cannot be tested against a boundary.
        cursor: The previous run's resume point, in whatever form that feed's
            walk uses. ``None`` on a first run.
        captured_through: Last day a windowed walk fully covered. ``None`` on a
            first run, which then starts at :attr:`floor`.
        floor: Earliest day worth asking for — our appetite, not WB's memory.
        max_windows: How many windows this run may walk.
        max_pages: How many pages of a cursor-paged stream this run may walk.
        max_rows: How many rows of a take/skip feed this run may capture.
    """

    today: date
    cursor: str | None = None
    captured_through: date | None = None
    floor: date = field(default_factory=lambda: date(2024, 1, 1))
    max_windows: int = 12
    max_pages: int = 8
    max_rows: int = 30000

    @property
    def yesterday(self) -> date:
        """The newest day WB will answer for — there is no data for today."""
        return self.today - timedelta(days=1)

    def resume_from(self) -> date:
        """Where a windowed walk starts: after the last covered day, or the floor."""
        if self.captured_through is None:
            return self.floor
        return max(self.floor, self.captured_through + timedelta(days=1))


@dataclass(frozen=True, slots=True)
class CaptureBatch:
    """One committable slice of a walk, and where it leaves the watermark.

    Attributes:
        rows: Captured rows, ready to upsert. May be empty — a batch that
            carries only a watermark is how a walk says "everything up to here
            is safely stored".
        cursor: Resume point, or ``None`` to leave the previous one alone.

            **Only set it where a resume from it would lose nothing.** The
            orders stream is the case that makes this a rule rather than a
            style: its cursor is the largest ``lastChangeDate`` in a page, and
            WB does not order the page by it, so the largest seen SO FAR is not
            a safe place to resume from — rows later in the same page can be
            older. So the stream yields rows as they arrive with no cursor, and
            the cursor once the page has ended.
        captured_through: Last day now fully covered, or ``None`` for a feed
            that does not walk days. Same rule: a window's day is safe only once
            that whole window has been yielded.
    """

    rows: list[CapturedRow] = field(default_factory=list)
    cursor: str | None = None
    captured_through: date | None = None


def windows(start: date, end: date, *, span_days: int, limit: int) -> Iterator[tuple[date, date]]:
    """Split ``[start, end]`` into inclusive windows of at most ``span_days``.

    WB's reference reports cap a request at 31 days and answer a wider one with
    HTTP 400, so a walk over history is a sequence of windows rather than one
    call. The ``limit`` is what keeps a first run — which may face three years
    of history — from holding a worker slot for an hour.

    Args:
        start: First day to cover.
        end: Last day to cover (inclusive).
        span_days: Window width WB permits.
        limit: How many windows to yield at most.

    Yields:
        ``(from, to)`` pairs, oldest first.
    """
    produced = 0
    cursor = start
    while cursor <= end and produced < limit:
        stop = min(cursor + timedelta(days=span_days - 1), end)
        yield cursor, stop
        cursor = stop + timedelta(days=1)
        produced += 1


def as_rows(payload: Any, *, key_of: Any, day_of: Any = None) -> list[CapturedRow]:
    """Turn a WB list payload into captured rows, skipping anything unusable.

    WB answers an empty window with ``204`` (decoded here as ``None``) on some
    feeds and ``{"report": []}`` on others, and a malformed row must not cost
    the whole window — so anything that is not an object with a usable key is
    dropped rather than raised on.

    Args:
        payload: The decoded WB body, or a list already dug out of it.
        key_of: Callable returning a row's stable identity.
        day_of: Callable returning the day a row is about, or ``None``.

    Returns:
        One tuple per usable row.
    """
    if not isinstance(payload, list):
        return []
    rows: list[CapturedRow] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            key = str(key_of(item))
        except (KeyError, TypeError, ValueError):
            continue
        if not key:
            continue
        day: date | None = None
        if day_of is not None:
            try:
                day = day_of(item)
            except (KeyError, TypeError, ValueError):
                day = None
        rows.append((key, day, item))
    return rows


def parse_day(value: Any) -> date | None:
    """Read a WB date or datetime string as a day, or ``None`` if it is neither.

    WB mixes ``2026-03-15``, ``2026-03-15T01:10:02`` and
    ``2026-03-15T01:10:02.123456Z`` across these feeds, sometimes inside one of
    them, so this takes the first ten characters rather than trusting a format.
    """
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


__all__ = [
    "CaptureBatch",
    "CaptureWindow",
    "CapturedRow",
    "as_rows",
    "parse_day",
    "windows",
]
