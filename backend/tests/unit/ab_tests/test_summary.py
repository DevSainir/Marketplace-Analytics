"""Unit tests for the test-level summary (ab_tests/services/summary.py).

The block's whole claim is that it is the result table's column sums, so the
tests here are mostly about the identity between the two rather than about
arithmetic that :mod:`test_metrics` already covers: if "Total impressions" can ever
differ from the sum of the "Impressions" row, the number is worse than absent,
because it looks checkable and is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.modules.ab_tests.services.results import build_rows
from src.modules.ab_tests.services.summary import build_summary

START = datetime(2026, 9, 8, 13, 0, tzinfo=UTC)


@dataclass
class FakeVariant:
    """A photo, as the two builders read one."""

    id: uuid.UUID
    position: int
    is_original: bool = False
    excluded_at: datetime | None = None

    @property
    def is_excluded(self) -> bool:
        """Mirrors the model's own property."""
        return self.excluded_at is not None


@dataclass
class FakeWindow:
    """One recorded polling interval."""

    variant_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = Decimal("0")


@dataclass
class FakeTest:
    """Only the fields the builders touch."""

    id: uuid.UUID
    active_variant_id: uuid.UUID | None


def _variants(count: int = 2) -> list[FakeVariant]:
    """`count` photos in rotation order, the first being the card's own."""
    return [
        FakeVariant(id=uuid.uuid4(), position=index, is_original=index == 0)
        for index in range(count)
    ]


def _five_minutes(variant_id: uuid.UUID, index: int, **counts: int) -> FakeWindow:
    """One five-minute window starting `index` slots after START."""
    start = START + timedelta(minutes=5 * index)
    return FakeWindow(
        variant_id=variant_id,
        window_start=start,
        window_end=start + timedelta(minutes=5),
        views=counts.get("views", 0),
        clicks=counts.get("clicks", 0),
        atbs=counts.get("atbs", 0),
        orders=counts.get("orders", 0),
        spend=Decimal(counts.get("spend", 0)),
    )


def test_totals_equal_the_sum_of_the_result_table() -> None:
    """Every count in the block is the sum of that column in the table.

    The one property the summary promises: a reader who adds the columns up
    lands on the same figures. Asserted against `build_rows` rather than against
    hand-written expectations, so a change to either builder that breaks the
    identity fails here rather than on someone's screen.
    """
    first, second = _variants()
    windows = [
        _five_minutes(first.id, 0, views=100, clicks=5, atbs=2, orders=1, spend=25),
        _five_minutes(first.id, 1, views=80, clicks=4, atbs=1, orders=0, spend=20),
        _five_minutes(second.id, 2, views=120, clicks=3, atbs=1, orders=1, spend=30),
    ]
    test = FakeTest(id=uuid.uuid4(), active_variant_id=second.id)

    rows = build_rows(
        test=test,  # type: ignore[arg-type]
        variants=[first, second],  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        image_url="/{test_id}/{variant_id}",
    )
    summary = build_summary(
        variants=[first, second],  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        rounds_completed=1,
    )

    assert summary.views == sum(row.views for row in rows) == 300
    assert summary.clicks == sum(row.clicks for row in rows) == 12
    assert summary.atbs == sum(row.atbs for row in rows) == 4
    assert summary.orders == sum(row.orders for row in rows) == 2
    assert summary.spend == sum((row.spend for row in rows), Decimal(0)) == Decimal(75)


def test_ratios_divide_the_totals_rather_than_averaging_the_rows() -> None:
    """CTR is Σclicks / Σviews, not the mean of the photos' own CTRs.

    The two answers differ whenever the photos got unequal traffic, and the mean
    is the one that flatters a photo which happened to run during a quiet hour.
    Here the per-photo CTRs are 10 % and 1 %; their mean is 5.5 % and the honest
    figure is 1.82 %.
    """
    first, second = _variants()
    windows = [
        _five_minutes(first.id, 0, views=100, clicks=10),
        _five_minutes(second.id, 1, views=1_000, clicks=10),
    ]

    summary = build_summary(
        variants=[first, second],  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        rounds_completed=1,
    )

    assert summary.views == 1_100
    assert summary.click_through == Decimal("1.82")


def test_measured_time_counts_the_windows_not_the_wall_clock() -> None:
    """Three five-minute windows spread over an hour measure fifteen minutes.

    The gap is the point: a test that was paused, or whose advertising stopped,
    accrues no windows over that stretch, and reporting the wall clock as the
    exposure would present an hour's worth of confidence in a quarter of an
    hour's data.
    """
    (only,) = _variants(1)
    windows = [
        _five_minutes(only.id, 0, views=10),
        _five_minutes(only.id, 6, views=10),
        _five_minutes(only.id, 11, views=10),
    ]

    summary = build_summary(
        variants=[only],  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        rounds_completed=1,
    )

    assert summary.measured_minutes == 15
    assert summary.windows == 3
    assert summary.first_window_at == START
    assert summary.last_window_at == START + timedelta(minutes=60)


def test_an_hour_served_by_two_campaigns_is_measured_once() -> None:
    """Two campaigns over the same windows measure the windows, not twice them.

    Each interval is stored once per campaign. Summing the rows reported a
    20-hour test with two campaigns as "1d 17h"; the time a photo was on the
    card does not grow with the number of campaigns showing it.
    """
    (only,) = _variants(1)
    windows = [
        _five_minutes(only.id, index, views=10) for index in range(3) for _campaign in range(2)
    ]

    summary = build_summary(
        variants=[only],  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        rounds_completed=1,
    )

    assert summary.measured_minutes == 15
    assert summary.views == 60


def test_a_test_with_nothing_measured_reports_no_ratios() -> None:
    """Zero counts give `None` ratios, never 0 %.

    Same rule the per-photo rows follow: "nothing to divide" and "divided, got
    zero" are different answers, and a summary that says 0 % CTR of a test that
    has not run yet reads as a failed test.
    """
    variants = _variants()

    summary = build_summary(
        variants=variants,  # type: ignore[arg-type]
        windows=[],
        rounds_completed=0,
    )

    assert summary.views == 0
    assert summary.click_through is None
    assert summary.measured_minutes == 0
    assert summary.first_window_at is None
    assert summary.variants_measured == 0
    assert summary.variants_total == 2


def test_only_photos_that_earned_impressions_count_as_measured() -> None:
    """The "2 of 5 photos" count is photos with traffic, not photos that were live.

    A photo installed into dead air has windows and no views; counting it would
    tell the seller five photos have been compared when four of them have
    nothing to compare with.
    """
    variants = _variants(3)
    windows = [
        _five_minutes(variants[0].id, 0, views=50, clicks=1),
        _five_minutes(variants[1].id, 1, views=0),
    ]

    summary = build_summary(
        variants=variants,  # type: ignore[arg-type]
        windows=windows,  # type: ignore[arg-type]
        rounds_completed=1,
    )

    assert summary.variants_measured == 1
    assert summary.variants_total == 3
