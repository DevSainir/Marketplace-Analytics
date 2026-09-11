"""How the P&L lane decides what to ask WB for, and where it resumes.

Two pieces, both of which have been wrong in production:

* the SPAN — which stretch of history is missing. Choosing it as "everything
  older than my oldest row" cannot see a hole in the middle, which is how NEVA
  ended up with 51 days of settlement rows spanning two years and a lane that
  called itself complete.
* the CURSOR — what survives sixteen hours, several deploys and a worker
  recreate.

Both ways of being wrong are silent, which is what makes them worth pinning.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.modules.finreports.tasks.backfill import (
    PNL_EMPTY_STOP,
    PNL_FLOOR_DAYS,
    PNL_GAP_TOLERANCE_DAYS,
    _format_cursor,
    _parse_cursor,
    next_span,
)

TODAY = date(2026, 9, 11)
FLOOR = TODAY - timedelta(days=PNL_FLOOR_DAYS)


def _days(*blocks: tuple[str, int]) -> list[date]:
    """Settlement days as (first day, count) blocks — the shape WB data has."""
    out: list[date] = []
    for first, count in blocks:
        start = date.fromisoformat(first)
        out.extend(start + timedelta(days=offset) for offset in range(count))
    return out


# --------------------------------------------------------------------------- #
# Choosing the span
# --------------------------------------------------------------------------- #
def test_a_workspace_with_nothing_stored_walks_the_whole_reachable_history() -> None:
    """A brand-new org has no coverage to reason from, so ask for all of it."""
    assert next_span([], search_from=FLOOR, today=TODAY) == (FLOOR, date(2026, 9, 10))


def test_a_hole_in_the_middle_is_found() -> None:
    """The case that cost NEVA two years of P&L.

    Its lane asked only "what is older than my oldest row?", so once it held the
    first block it believed itself finished — over everything after it.

    The pre-history hole is offered first and that is correct: oldest gap wins,
    and WB simply answers it empty. What matters is that the walk then moves ON
    to the real one instead of stopping.
    """
    stored = _days(("2024-07-11", 45), ("2026-08-09", 29))

    prehistory = next_span(stored, search_from=FLOOR, today=TODAY)
    assert prehistory == (FLOOR, date(2024, 7, 10))

    after_prehistory = next_span(stored, search_from=prehistory[1] + timedelta(days=1), today=TODAY)

    assert after_prehistory == (date(2024, 8, 25), date(2026, 8, 8))


def test_a_hole_before_the_oldest_row_is_found() -> None:
    """The original behaviour has to survive: a late joiner has history behind them."""
    stored = _days(("2026-06-25", 78))

    assert next_span(stored, search_from=FLOOR, today=TODAY) == (FLOOR, date(2026, 6, 24))


def test_quiet_days_between_weekly_reports_are_not_holes() -> None:
    """WB forms about one report a week, so most days legitimately have no rows.

    Measured across the four healthy workspaces on 2026-09-11: biggest gap 1-2
    days. A lane that treated those as holes would walk for ever re-asking for
    days WB has already answered.
    """
    weekly = [date(2026, 6, 1) + timedelta(days=offset * 7) for offset in range(14)]

    assert next_span(weekly, search_from=weekly[0], today=TODAY) is None
    assert PNL_GAP_TOLERANCE_DAYS >= 14


def test_a_span_already_concluded_is_not_offered_again() -> None:
    """Otherwise a stretch WB will never serve is re-probed for ever.

    ``search_from`` moves past a span the walk exhausted, so the next tick looks
    BEYOND it instead of starting the same three empty probes again.
    """
    stored = _days(("2024-07-11", 45), ("2025-06-01", 30), ("2026-08-09", 29))
    first = next_span(stored, search_from=FLOOR, today=TODAY)
    assert first is not None

    second = next_span(stored, search_from=first[1] + timedelta(days=1), today=TODAY)

    assert second is not None
    assert second[0] > first[1]


def test_days_after_the_newest_row_belong_to_the_forward_harvest() -> None:
    """Two walks writing the same weeks from opposite ends is not a backfill."""
    stored = _days(("2026-08-01", 10))

    assert next_span(stored, search_from=date(2026, 8, 1), today=TODAY) is None


# --------------------------------------------------------------------------- #
# The cursor
# --------------------------------------------------------------------------- #
def test_the_cursor_round_trips_every_field() -> None:
    """It has to still be correct sixteen hours and several deploys later."""
    span_from, span_to, search_from = date(2024, 8, 25), date(2026, 8, 8), date(2024, 7, 12)

    restored = _parse_cursor(_format_cursor(span_from, span_to, 2658647303922, 2, search_from))

    assert restored == (span_from, span_to, 2658647303922, 2, search_from)


def test_every_older_cursor_shape_still_parses() -> None:
    """A field is always added while some lane is mid-walk.

    A parser that demanded the newest shape would turn every in-flight lane into
    a failing tick at the moment of deploy — trading a cosmetic gap for the exact
    silent death this lane keeps being fixed for.
    """
    three_part = _parse_cursor("2024-08-25|2026-08-08|42")
    four_part = _parse_cursor("2024-08-25|2026-08-08|42|2")

    assert three_part == (date(2024, 8, 25), date(2026, 8, 8), 42, 0, date(2024, 8, 25))
    assert four_part[3] == 2


def test_a_walk_needs_several_empty_answers_before_it_believes_them() -> None:
    """One 204 is WB being quiet; three in a row, fifteen minutes apart, is an end."""
    assert PNL_EMPTY_STOP >= 3
