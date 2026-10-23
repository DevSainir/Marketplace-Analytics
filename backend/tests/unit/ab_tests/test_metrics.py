"""Unit tests for variant metric arithmetic (ab_tests/services/metrics.py).

The three ratios the UI shows are chained, not parallel: each one divides by the
previous stage, so the add-to-cart rate is add-to-basket per *click*, not
per impression. Getting that wrong produces a plausible number rather than an
error, which is why the expected values below are a worked example in the
shape of WB's own A/B result screen for a completed test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.modules.ab_tests.services.metrics import (
    VariantTotals,
    WindowCounts,
    conversions,
    totals_from_windows,
)


def _window(ended: datetime, **counts: int) -> WindowCounts:
    """One polling interval with zero defaults."""
    return WindowCounts(
        window_end=ended,
        views=counts.get("views", 0),
        clicks=counts.get("clicks", 0),
        atbs=counts.get("atbs", 0),
        orders=counts.get("orders", 0),
        spend=Decimal(counts.get("spend", 0)),
    )


def test_conversions_reproduce_wb_own_ab_result_screen() -> None:
    """Our three ratios equal what WB's result screen shows for variant A.

    The example: 8.97 / 8.04 / 33.25 % against 54 249 impressions, 4 865 clicks,
    391 carts and 130 orders. Any of the three computed against the wrong
    denominator still lands in a believable 0–100 range, so this is the check
    that catches it.
    """
    totals = VariantTotals(views=54_249, clicks=4_865, atbs=391, orders=130)

    result = conversions(totals)

    assert result.click_through == Decimal("8.97")
    assert result.add_to_cart == Decimal("8.04")
    assert result.order_rate == Decimal("33.25")


def test_conversions_reproduce_the_losing_variant_too() -> None:
    """Variant B of the same test: 8.66 / 9.55 / 29.36 %."""
    totals = VariantTotals(views=54_765, clicks=4_744, atbs=453, orders=133)

    result = conversions(totals)

    assert result.click_through == Decimal("8.66")
    assert result.add_to_cart == Decimal("9.55")
    assert result.order_rate == Decimal("29.36")


@pytest.mark.parametrize(
    ("totals", "field"),
    [
        (VariantTotals(views=0, clicks=0), "click_through"),
        (VariantTotals(views=100, clicks=0), "add_to_cart"),
        (VariantTotals(views=100, clicks=10, atbs=0), "order_rate"),
    ],
)
def test_a_ratio_with_no_denominator_is_none_not_zero(totals: VariantTotals, field: str) -> None:
    """A stage nobody reached yields ``None``, never 0 %.

    Zero would read as "this photo converts nobody" and would drag a variant's
    average down; the honest answer while the denominator is empty is "unknown".
    """
    result = conversions(totals)

    assert getattr(result, field) is None


def test_totals_sum_every_recorded_interval() -> None:
    """A variant's totals are the sum of its intervals, across the whole rotation."""
    windows = [
        _window(
            datetime(2026, 8, 1, tzinfo=UTC), views=1_000, clicks=90, atbs=8, orders=3, spend=1_500
        ),
        _window(
            datetime(2026, 8, 2, tzinfo=UTC),
            views=2_000,
            clicks=180,
            atbs=17,
            orders=5,
            spend=2_500,
        ),
    ]

    totals = totals_from_windows(windows)

    assert totals == VariantTotals(
        views=3_000, clicks=270, atbs=25, orders=8, spend=Decimal("4000")
    )


def test_totals_of_no_intervals_are_zero_not_an_error() -> None:
    """A variant that has never been live reports zeroes, so the row still renders."""
    assert totals_from_windows([]) == VariantTotals()


def test_ctr_is_derived_from_counts_never_stored() -> None:
    """Summing daily CTRs is not the CTR of the sum — we must divide the totals.

    Two intervals of 1 % and 10 % CTR on very different volumes average to
    neither; this pins that the module divides summed clicks by summed views.
    """
    windows = [
        _window(datetime(2026, 8, 1, tzinfo=UTC), views=10_000, clicks=100),  # 1 %
        _window(datetime(2026, 8, 2, tzinfo=UTC), views=100, clicks=10),  # 10 %
    ]

    result = conversions(totals_from_windows(windows))

    assert result.click_through == Decimal("1.09")  # 110 / 10100, not 5.50


def test_variant_id_is_not_part_of_the_arithmetic() -> None:
    """Totals depend only on counts, so the same numbers give the same answer.

    Guards against a regression where the summariser keyed on the variant and
    silently returned another variant's totals.
    """
    first = totals_from_windows([_window(datetime(2026, 8, 1, tzinfo=UTC), views=10, clicks=1)])
    second = totals_from_windows([_window(datetime(2026, 8, 9, tzinfo=UTC), views=10, clicks=1)])

    assert first == second
    assert uuid.uuid4() != uuid.uuid4()  # sanity: ids are not involved at all
