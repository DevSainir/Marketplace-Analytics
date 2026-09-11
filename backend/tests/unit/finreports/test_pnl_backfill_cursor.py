"""The P&L lane's cursor: the one piece of it that survives a restart.

Everything else about that lane is a WB call and a commit. The cursor is the
part that has to still be correct sixteen hours and several deploys later, and
the two ways it can be wrong are both silent: a span that moves as the walk
fills it, and a resume point that re-reads or skips a page.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.finreports.tasks.backfill import (
    PNL_FLOOR_DAYS,
    _format_cursor,
    _parse_cursor,
    initial_span,
)


def test_the_span_ends_where_the_data_we_already_hold_begins() -> None:
    """A workspace mid-harvest backfills only what is behind it.

    Its forward harvest has been walking for weeks; asking WB again for those
    days would spend a fifteen-minute window per page to rewrite rows we have.
    """
    today = date(2026, 9, 10)

    span_from, span_to = initial_span(earliest_held=date(2026, 8, 9), today=today)

    assert span_to == date(2026, 8, 8)
    assert span_from == today - timedelta(days=PNL_FLOOR_DAYS)


def test_a_workspace_with_no_settlement_rows_walks_up_to_yesterday() -> None:
    """A brand-new org has nothing to stop short of, and WB serves no today."""
    today = date(2026, 9, 10)

    _, span_to = initial_span(earliest_held=None, today=today)

    assert span_to == date(2026, 9, 9)


def test_the_cursor_carries_the_span_so_the_denominator_cannot_move() -> None:
    """The span round-trips whole, not just the page pointer.

    Recomputing the span each tick is the obvious implementation and it makes
    the progress bar walk backwards: every ingested page moves ``earliest_held``
    older, which shortens the very span the percentage divides by.
    """
    span_from, span_to, rrd_id = date(2021, 9, 11), date(2026, 8, 8), 2658647303922

    restored = _parse_cursor(_format_cursor(span_from, span_to, rrd_id))

    assert restored[:3] == (span_from, span_to, rrd_id)


def test_a_fresh_cursor_starts_at_page_zero() -> None:
    """``rrdid=0`` is WB's "from the beginning", and it must survive the trip."""
    assert _parse_cursor(_format_cursor(date(2024, 1, 1), date(2026, 1, 1), 0))[2] == 0


def test_the_cursor_carries_the_empty_streak_and_survives_the_older_form() -> None:
    """One empty answer must not be able to end a walk, so it has to be counted.

    WB answers an exhausted window and a window it is briefly not serving with
    the same `204 No Content`. On 2026-09-11 a tick mid-span believed the first
    one and marked NEVA's P&L complete over a 715-day hole.

    Lanes already walking carry a three-part cursor, so the parser has to accept
    it — otherwise the fix turns every in-flight lane into a failing tick.
    """
    span_from, span_to = date(2021, 9, 12), date(2026, 8, 8)

    assert _parse_cursor(_format_cursor(span_from, span_to, 42, 2)) == (
        span_from,
        span_to,
        42,
        2,
    )
    assert _parse_cursor(f"{span_from}|{span_to}|42") == (span_from, span_to, 42, 0)


def test_a_walk_needs_several_empty_answers_before_it_believes_them() -> None:
    """One 204 is WB being quiet; three in a row, fifteen minutes apart, is an end."""
    from src.modules.finreports.tasks.backfill import PNL_EMPTY_STOP

    assert PNL_EMPTY_STOP >= 3
