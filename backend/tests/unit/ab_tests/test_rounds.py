"""Unit tests for the per-lap columns (services/rounds.py).

«Кругов» and the gap to the leader. «Побед в раундах» used to be computed here
too and was removed on 2026-09-28; its tests went with it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.modules.ab_tests.models import VariantExposure, VariantStatWindow
from src.modules.ab_tests.services.rounds import gap_to_best, standings

T0 = datetime(2026, 9, 8, 9, 0, tzinfo=UTC)
A, B = uuid.uuid4(), uuid.uuid4()


def _exposure(variant_id: uuid.UUID, *, lap: int, start: int, end: int | None) -> VariantExposure:
    """One turn, positioned in minutes from ``T0``."""
    return VariantExposure(
        test_id=uuid.uuid4(),
        variant_id=variant_id,
        round_number=lap,
        activated_at=T0 + timedelta(minutes=start),
        deactivated_at=None if end is None else T0 + timedelta(minutes=end),
    )


def _window(variant_id: uuid.UUID, *, at: int, views: int, clicks: int) -> VariantStatWindow:
    """One measured interval, closing ``at`` minutes after ``T0``."""
    return VariantStatWindow(
        test_id=uuid.uuid4(),
        variant_id=variant_id,
        window_start=T0 + timedelta(minutes=at - 5),
        window_end=T0 + timedelta(minutes=at),
        views=views,
        clicks=clicks,
    )


def test_every_lap_a_photo_was_dealt_in_counts_as_played() -> None:
    """Three turns each is three laps each, whatever the traffic did."""
    exposures = [
        _exposure(A, lap=1, start=0, end=20),
        _exposure(B, lap=1, start=20, end=40),
        _exposure(A, lap=2, start=40, end=60),
        _exposure(B, lap=2, start=60, end=80),
        _exposure(A, lap=3, start=80, end=100),
        _exposure(B, lap=3, start=100, end=None),
    ]
    windows = [_window(A, at=20, views=1000, clicks=100)]

    result = standings(variant_ids=[A, B], windows=windows, exposures=exposures)

    assert result[A].rounds_played == result[B].rounds_played == 3


def test_one_campaign_counts_only_the_laps_it_brought_traffic_in() -> None:
    """Filtered to one campaign, a lap with no window of it was not played."""
    exposures = [_exposure(A, lap=1, start=0, end=20), _exposure(A, lap=2, start=40, end=None)]
    windows = [_window(A, at=20, views=1000, clicks=50)]

    result = standings(
        variant_ids=[A], windows=windows, exposures=exposures, played_from_windows=True
    )

    assert result[A].rounds_played == 1


def test_a_photo_excluded_mid_test_keeps_the_laps_it_played() -> None:
    """Excluding is not deleting: the record it earned stays on the table."""
    exposures = [
        _exposure(A, lap=1, start=0, end=20),
        _exposure(B, lap=1, start=20, end=40),
        _exposure(A, lap=2, start=40, end=None),
    ]
    windows = [
        _window(A, at=20, views=1000, clicks=50),
        _window(B, at=40, views=1000, clicks=10),
        _window(A, at=60, views=1000, clicks=50),
    ]

    result = standings(variant_ids=[A, B], windows=windows, exposures=exposures)

    assert result[B].rounds_played == 1
    assert result[A].rounds_played == 2


def test_a_photo_that_never_ran_stands_at_zero_rather_than_missing() -> None:
    """Every photo gets a row, so every photo needs a standing."""
    result = standings(variant_ids=[A, B], windows=[], exposures=[])

    assert result[A].rounds_played == 0
    assert result[B].rounds_played == 0


def test_the_leader_is_zero_behind_itself_rather_than_unmeasured() -> None:
    """«—» in the leader's own gap column would read as a missing number."""
    assert gap_to_best(Decimal("3.34"), Decimal("3.34")) == (Decimal("0.00"), Decimal("0.00"))


def test_the_gap_is_reported_both_in_points_and_relative_to_the_leader() -> None:
    """1.25 pp behind 3.34 % is 37 % less click-through, and both are wanted.

    The points figure is what the numbers literally differ by; the relative one
    is the sentence a seller can act on.
    """
    absolute, relative = gap_to_best(Decimal("2.09"), Decimal("3.34"))

    assert absolute == Decimal("1.25")
    assert relative == Decimal("-37.43")


def test_an_unmeasured_photo_has_no_gap_at_all() -> None:
    """«Behind by an unknown amount» is not a number, and 0 would be a lie."""
    assert gap_to_best(None, Decimal("3.34")) == (None, None)
    assert gap_to_best(Decimal("3.34"), None) == (None, None)
