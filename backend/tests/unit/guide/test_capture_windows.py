"""The window arithmetic every captured feed resumes from."""

from __future__ import annotations

from datetime import date

from src.modules.guide.services.fetch import CaptureWindow, as_rows, parse_day, windows


def test_a_first_run_starts_at_the_floor_not_at_the_beginning_of_time() -> None:
    """With no watermark the walk starts at our own history floor.

    The floor is a bound on OUR appetite, not on WB's memory: these feeds serve
    the account's whole history, so without it a first run would walk from 1970.
    """
    window = CaptureWindow(today=date(2026, 9, 12), floor=date(2024, 1, 1))

    assert window.resume_from() == date(2024, 1, 1)


def test_a_later_run_resumes_the_day_after_the_last_one_covered() -> None:
    """Resuming ON the last covered day would re-read it every single run."""
    window = CaptureWindow(
        today=date(2026, 9, 12), captured_through=date(2026, 8, 31), floor=date(2024, 1, 1)
    )

    assert window.resume_from() == date(2026, 9, 1)


def test_a_watermark_older_than_the_floor_does_not_drag_the_walk_back() -> None:
    """The floor wins over a stale watermark.

    Shortening the history floor must not make the next run re-walk years the
    previous configuration had already covered.
    """
    window = CaptureWindow(
        today=date(2026, 9, 12), captured_through=date(2020, 1, 1), floor=date(2024, 1, 1)
    )

    assert window.resume_from() == date(2024, 1, 1)


def test_the_newest_day_asked_for_is_yesterday() -> None:
    """WB has no data for today — every one of these feeds ends at yesterday."""
    window = CaptureWindow(today=date(2026, 9, 12))

    assert window.yesterday == date(2026, 9, 11)


def test_windows_are_inclusive_and_never_wider_than_wb_allows() -> None:
    """A 31-day cap means 31 days counted inclusively, not 32.

    WB answers a wider window with HTTP 400, so an off-by-one here turns every
    walk into a run of errors rather than a run of slightly wrong data.
    """
    spans = list(windows(date(2026, 1, 1), date(2026, 3, 3), span_days=31, limit=10))

    assert spans[0] == (date(2026, 1, 1), date(2026, 1, 31))
    assert spans[1] == (date(2026, 2, 1), date(2026, 3, 3))
    assert all((stop - start).days < 31 for start, stop in spans)


def test_the_window_budget_stops_a_first_run_walking_three_years() -> None:
    """The limit bounds one run; the watermark carries the rest to the next.

    Three windows of 31 days reach 2024-04-02, not 2026 — which is the point: a
    first run over a three-year account is a backfill spread across several
    months of runs rather than one that holds a worker slot for an hour.
    """
    spans = list(windows(date(2024, 1, 1), date(2026, 9, 11), span_days=31, limit=3))

    assert len(spans) == 3
    assert spans[-1][1] == date(2024, 4, 2)


def test_an_exhausted_range_yields_nothing() -> None:
    """A walk that has already reached yesterday asks WB for nothing at all."""
    spans = list(windows(date(2026, 9, 12), date(2026, 9, 11), span_days=31, limit=10))

    assert spans == []


def test_a_row_without_a_usable_key_is_dropped_rather_than_raised_on() -> None:
    """One malformed row must not cost the whole window.

    These feeds are captured, not validated — a walk that raises on a surprise
    field loses every good row beside it, which is the opposite of the point.
    """
    payload = [
        {"srid": "a1", "date": "2026-03-15T01:10:02"},
        {"no_key_here": 1},
        "not an object",
        {"srid": "", "date": "2026-03-15"},
    ]

    rows = as_rows(payload, key_of=lambda item: item["srid"], day_of=lambda i: parse_day(i["date"]))

    assert [key for key, _, _ in rows] == ["a1"]
    assert rows[0][1] == date(2026, 3, 15)


def test_a_204_is_captured_as_nothing_not_as_a_failure() -> None:
    """WB answers an empty window with 204, decoded as ``None``."""
    assert as_rows(None, key_of=lambda item: item["id"]) == []


def test_wb_date_formats_are_all_read_as_the_same_day() -> None:
    """WB mixes three stamp formats, sometimes inside one feed."""
    assert parse_day("2026-03-15") == date(2026, 3, 15)
    assert parse_day("2026-03-15T01:10:02") == date(2026, 3, 15)
    assert parse_day("2026-08-29T18:14:36.239416") == date(2026, 3, 15).replace(month=8, day=29)
    assert parse_day("") is None
    assert parse_day(None) is None
    assert parse_day("not-a-date") is None
