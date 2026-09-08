"""Unit tests for the per-lap columns (services/rounds.py).

«Побед в раундах» exists because totals lie in one specific way: a photo that
happened to be up during a good hour carries a high CTR for the whole test on
the strength of one lap. Counting laps makes that one vote instead of a
multiplier — so the case that matters here is the one where the two answers
disagree, and the table has to be able to show both.
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


def test_a_photo_can_win_the_test_on_totals_and_still_lose_most_laps() -> None:
    """The disagreement the column exists for.

    A earns one enormous lap and loses the other two. Its total CTR is the best
    in the test; its record is 1-2. Both are true, and «побед» is the one that
    survives the good hour being a coincidence.
    """
    exposures = [
        _exposure(A, lap=1, start=0, end=20),
        _exposure(B, lap=1, start=20, end=40),
        _exposure(A, lap=2, start=40, end=60),
        _exposure(B, lap=2, start=60, end=80),
        _exposure(A, lap=3, start=80, end=100),
        _exposure(B, lap=3, start=100, end=None),
    ]
    windows = [
        _window(A, at=20, views=1000, clicks=100),  # 10 % — a great lap
        _window(B, at=40, views=1000, clicks=30),
        _window(A, at=60, views=1000, clicks=20),
        _window(B, at=80, views=1000, clicks=30),
        _window(A, at=100, views=1000, clicks=20),
        _window(B, at=120, views=1000, clicks=30),
    ]

    result = standings(variant_ids=[A, B], windows=windows, exposures=exposures)

    assert result[A].rounds_won == 1
    assert result[B].rounds_won == 2
    assert result[A].rounds_played == result[B].rounds_played == 3


def test_a_lap_nobody_was_measured_in_is_won_by_nobody() -> None:
    """Zero impressions is «not measured», not a 0 % anyone can beat."""
    exposures = [_exposure(A, lap=1, start=0, end=20), _exposure(B, lap=1, start=20, end=40)]
    windows = [_window(A, at=20, views=0, clicks=0)]

    result = standings(variant_ids=[A, B], windows=windows, exposures=exposures)

    assert result[A].rounds_won == 0
    assert result[B].rounds_won == 0


def test_a_tied_lap_is_won_by_nobody_rather_than_by_everybody() -> None:
    """Two identical photos did not each beat the other.

    Crediting both would make the wins stop summing to the number of laps, and
    the column would read as «laps in which this photo was not beaten».
    """
    exposures = [_exposure(A, lap=1, start=0, end=20), _exposure(B, lap=1, start=20, end=40)]
    windows = [
        _window(A, at=20, views=1000, clicks=50),
        _window(B, at=40, views=1000, clicks=50),
    ]

    result = standings(variant_ids=[A, B], windows=windows, exposures=exposures)

    assert (result[A].rounds_won, result[B].rounds_won) == (0, 0)


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
    assert result[B].rounds_won == 0


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
