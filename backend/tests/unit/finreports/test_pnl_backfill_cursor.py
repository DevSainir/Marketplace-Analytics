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
    PNL_GAP_TOLERANCE_DAYS,
    _format_cursor,
    _parse_cursor,
    next_span,
)
from src.modules.finreports.tasks.backfill.span import PNL_SPAN_CHUNK_DAYS

TODAY = date(2026, 9, 11)

#: These cases reproduce NEVA's real history, which spans two years, so they pass
#: their own floor rather than the product's. The depth WB is asked for is a
#: business decision (:data:`PNL_FLOOR_DAYS`, three months) and the gap-finder's
#: correctness is not — tying them together would mean every future change to
#: how much history a new seller gets silently rewrote these regressions.
FLOOR = date(2021, 9, 12)


def _days(*blocks: tuple[str, int]) -> list[date]:
    """Settlement days as (first day, count) blocks — the shape WB data has."""
    out: list[date] = []
    for first, count in blocks:
        start = date.fromisoformat(first)
        out.extend(start + timedelta(days=offset) for offset in range(count))
    return out


# --------------------------------------------------------------------------- #
# Choosing the span — newest first
# --------------------------------------------------------------------------- #
def test_a_workspace_with_nothing_stored_starts_at_the_newest_end() -> None:
    """A brand-new org has no coverage to reason from, so start where it matters.

    Not "the whole reachable history": a backfill is interrupted far more often
    than it finishes, and the seller wants this month's P&L rather than the
    archive. The first span is the newest chunk inside the depth.
    """
    span = next_span([], search_to=TODAY, today=TODAY, floor=FLOOR)

    assert span is not None
    assert span[1] == TODAY - timedelta(days=1)
    assert (span[1] - span[0]).days + 1 == PNL_SPAN_CHUNK_DAYS


def test_the_newest_hole_is_taken_before_the_oldest() -> None:
    """NEVA's shape, and the direction that would have saved it.

    Its history is a 45-day block in 2024, a 715-day hole, then recent weeks.
    Walking oldest-first, the lane spent thirteen hours in 2024 and was stopped
    holding nothing from the summer anyone would look at. The hole nearest today
    is the one worth having.
    """
    stored = _days(("2024-07-11", 45), ("2026-08-09", 29))

    span = next_span(stored, search_to=TODAY, today=TODAY, floor=FLOOR)

    assert span is not None
    assert span[1] == date(2026, 8, 8), "took an older hole before the newest one"
    assert span[0] > date(2024, 8, 25), "swallowed the whole gap in one span"


def test_a_long_gap_is_walked_in_chunks_from_its_newest_end() -> None:
    """Choosing the newest hole is not enough on its own.

    WB pages a window by ascending ``rrdid`` and offers no reverse, so a single
    span covering the whole gap would still deliver its oldest days first — and
    an interrupted walk would again leave the recent months missing. The chunk
    is what makes the ordering real.
    """
    stored = _days(("2024-07-11", 45), ("2026-08-09", 29))

    first = next_span(stored, search_to=TODAY, today=TODAY, floor=FLOOR)
    assert first is not None
    second = next_span(stored, search_to=first[0] - timedelta(days=1), today=TODAY, floor=FLOOR)

    assert second is not None
    assert (first[1] - first[0]).days + 1 <= PNL_SPAN_CHUNK_DAYS
    assert second[1] < first[0], "the walk did not move backwards"


def test_a_hole_before_the_oldest_row_is_still_reached_eventually() -> None:
    """Newest-first must not mean the deep history becomes unreachable.

    Once the ceiling has walked back past everything newer, the stretch before
    the seller's first stored row is offered like any other hole.
    """
    stored = _days(("2026-06-25", 78))

    span = next_span(stored, search_to=date(2026, 6, 24), today=TODAY, floor=FLOOR)

    assert span is not None
    assert span[1] == date(2026, 6, 24)


def test_quiet_days_between_weekly_reports_are_not_holes() -> None:
    """WB forms about one report a week, so most days legitimately have no rows.

    Measured across the four healthy workspaces on 2026-09-11: biggest gap 1-2
    days. A lane that treated those as holes would walk for ever re-asking for
    days WB has already answered.
    """
    weekly = [date(2026, 6, 1) + timedelta(days=offset * 7) for offset in range(14)]

    assert next_span(weekly, search_to=TODAY, today=TODAY, floor=weekly[0]) is None
    assert PNL_GAP_TOLERANCE_DAYS >= 14


def test_a_span_already_concluded_is_not_offered_again() -> None:
    """Otherwise a stretch WB will never serve is re-probed for ever.

    ``search_to`` moves BELOW a span the walk exhausted, so the next tick looks
    further back instead of starting the same three empty probes again.
    """
    stored = _days(("2024-07-11", 45), ("2025-06-01", 30), ("2026-08-09", 29))
    first = next_span(stored, search_to=TODAY, today=TODAY, floor=FLOOR)
    assert first is not None

    second = next_span(stored, search_to=first[0] - timedelta(days=1), today=TODAY, floor=FLOOR)

    assert second is not None
    assert second[1] < first[0]


def test_days_after_the_newest_row_belong_to_the_forward_harvest() -> None:
    """Two walks writing the same weeks from opposite ends is not a backfill.

    This matters more now the backfill starts at the newest end: without the
    rule the two would begin on the very same days.
    """
    stored = _days(("2026-08-01", 10))

    assert next_span(stored, search_to=TODAY, today=TODAY, floor=date(2026, 8, 1)) is None


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
