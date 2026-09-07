"""Unit tests for the rotation decision (ab_tests/services/rotation.py).

The rotation is the whole product: a photo stays on the card until its turn is
over, then the next one goes up. What ends a turn is one of **two mutually
exclusive** triggers, and most of this file is about that exclusivity — a test
configured by impressions must ignore the clock entirely, and one configured by
time must ignore the counter, because "whichever comes first" would judge the
variants on different exposures and make the comparison meaningless.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.services.rotation import (
    RotationAction,
    RotationState,
    decide,
)

VARIANTS = [
    uuid.UUID("00000000-0000-7000-8000-00000000000a"),
    uuid.UUID("00000000-0000-7000-8000-00000000000b"),
    uuid.UUID("00000000-0000-7000-8000-00000000000c"),
]

BUDGET = 10_000
SLOT_MINUTES = 60
NOW = datetime(2026, 9, 4, 13, 40, tzinfo=UTC)


def _state(
    *,
    active: uuid.UUID | None,
    impressions: int = 0,
    variants: list[uuid.UUID] | None = None,
    budget: int = BUDGET,
    mode: TriggerMode = TriggerMode.IMPRESSIONS,
    active_since: datetime | None = None,
    slot_minutes: int = SLOT_MINUTES,
    now: datetime = NOW,
) -> RotationState:
    """A rotation state with the module's defaults."""
    return RotationState(
        active_variant_id=active,
        variant_ids=variants if variants is not None else VARIANTS,
        trigger_mode=mode.value,
        impressions_for_active=impressions,
        impression_budget=budget,
        active_since=active_since,
        slot_minutes=slot_minutes,
        now=now,
    )


# --------------------------------------------------------------------------- #
# Trigger: impressions
# --------------------------------------------------------------------------- #


def test_the_photo_changes_once_the_impression_budget_is_reached() -> None:
    """At the budget the next variant is installed.

    The product's central promise: the picture rotates, and it rotates on the
    audience each photo actually got rather than on elapsed time.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=10_000))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_one_impression_short_of_the_budget_holds() -> None:
    """9 999 is not 10 000 — the photo stays put.

    The boundary matters because traffic arrives in lumps: a variant can sit
    just under budget across several polls and must not rotate early.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=9_999))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id == VARIANTS[0]


def test_overshooting_the_budget_still_advances_exactly_one_step() -> None:
    """An interval that lands four budgets' worth advances by one, not four.

    Skipping variants proportionally would leave photos in the rotation that
    were never shown to anybody.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=41_337))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_an_impression_test_ignores_the_clock_entirely() -> None:
    """A photo well past its slot length does NOT rotate on impressions mode.

    This is the exclusivity, in the direction that would be easiest to get
    wrong: the state still carries ``active_since`` and ``slot_minutes``,
    because the same dataclass serves both modes, and the impressions branch
    must not read them.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            impressions=10,
            active_since=NOW - timedelta(days=3),
        )
    )

    assert decision.action is RotationAction.HOLD


# --------------------------------------------------------------------------- #
# Trigger: time
# --------------------------------------------------------------------------- #


def test_the_photo_changes_once_the_slot_has_elapsed() -> None:
    """A time test rotates when the photo has been up for its slot."""
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=60),
        )
    )

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_a_minute_short_of_the_slot_holds() -> None:
    """The slot is measured from the install, not rounded to the poll."""
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=59),
        )
    )

    assert decision.action is RotationAction.HOLD


def test_a_slot_a_hair_short_still_counts() -> None:
    """The poll that lands milliseconds early must not cost a whole period.

    Both the install and this question are stamped with their Celery pass's
    start time, so a slot that is a whole number of poll periods — 5, 10, 30,
    60 minutes, every value anyone picks — is decided by which of two passes
    started later. Measured on production 2026-09-07, consecutive passes drift
    by up to ~14 ms. Losing that coin flip made an observed five-minute slot run
    ten minutes.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=60) + timedelta(milliseconds=14),
        )
    )

    assert decision.action is RotationAction.ADVANCE


def test_the_tolerance_does_not_swallow_a_real_wait() -> None:
    """It absorbs scheduling jitter, not a slot that genuinely has not run.

    Half a minute short is a photo still serving its turn; only the last few
    seconds are forgiven, and they are two orders of magnitude below the poll
    period, so nothing rotates a pass early.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(seconds=30),
            slot_minutes=5,
        )
    )

    assert decision.action is RotationAction.HOLD


def test_an_impression_budget_gets_no_tolerance() -> None:
    """Only the clock is forgiven. Impressions are counted, not scheduled.

    A budget that fired early would measure the arms over different exposures,
    which is the one thing the budget exists to prevent — and unlike a slot,
    nothing about a counter drifts with when the poll happened to run.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            impressions=BUDGET - 1,
            mode=TriggerMode.IMPRESSIONS,
        )
    )

    assert decision.action is RotationAction.HOLD


def test_a_time_test_ignores_the_impression_counter_entirely() -> None:
    """A photo far past the impression budget does NOT rotate in time mode.

    The other half of the exclusivity. A card with heavy advertising would
    otherwise blow through its slots in minutes, which is precisely the
    behaviour someone chose time mode to avoid.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            impressions=10_000_000,
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=5),
        )
    )

    assert decision.action is RotationAction.HOLD


def test_a_time_test_with_no_open_exposure_holds() -> None:
    """With nothing installed there is no clock to read, so nothing advances.

    Guards the arithmetic against ``None``: a test whose install failed has an
    active variant on the row but no open exposure until the retry succeeds.
    """
    decision = decide(_state(active=VARIANTS[0], mode=TriggerMode.TIME, active_since=None))

    assert decision.action is RotationAction.HOLD


def test_a_time_test_completes_after_its_last_slot() -> None:
    """Time mode ends the test the same way impressions mode does."""
    decision = decide(
        _state(
            active=VARIANTS[-1],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=120),
        )
    )

    assert decision.action is RotationAction.COMPLETE


@pytest.mark.parametrize("slot", [5, 30, 60, 1440])
def test_the_slot_length_is_configurable_per_test(slot: int) -> None:
    """60 minutes is the default, not a constant baked into the decision."""
    at_slot = _state(
        active=VARIANTS[0],
        mode=TriggerMode.TIME,
        slot_minutes=slot,
        active_since=NOW - timedelta(minutes=slot),
    )
    just_under = _state(
        active=VARIANTS[0],
        mode=TriggerMode.TIME,
        slot_minutes=slot,
        active_since=NOW - timedelta(minutes=slot - 1),
    )

    assert decide(at_slot).action is RotationAction.ADVANCE
    assert decide(just_under).action is RotationAction.HOLD


# --------------------------------------------------------------------------- #
# Shared lifecycle
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", [TriggerMode.IMPRESSIONS, TriggerMode.TIME])
def test_a_test_with_no_active_photo_installs_the_first_variant(mode: TriggerMode) -> None:
    """Starting a test puts variant 1 on the card, whichever trigger it uses."""
    decision = decide(_state(active=None, mode=mode))

    assert decision.action is RotationAction.INSTALL
    assert decision.variant_id == VARIANTS[0]


def test_the_last_variant_completes_the_test_instead_of_wrapping() -> None:
    """After the final photo meets its trigger the test is finished.

    Wrapping around silently would keep rewriting the seller's card forever; a
    second round has to be started deliberately.
    """
    decision = decide(_state(active=VARIANTS[-1], impressions=10_000))

    assert decision.action is RotationAction.COMPLETE
    assert decision.variant_id is None


def test_a_test_with_no_variants_cannot_start() -> None:
    """An empty test is a configuration error, not a rotation that completes."""
    decision = decide(_state(active=None, variants=[]))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id is None


def test_a_single_variant_test_completes_at_its_trigger() -> None:
    """One photo is a valid, if pointless, test — it must still terminate."""
    decision = decide(_state(active=VARIANTS[0], impressions=10_000, variants=VARIANTS[:1]))

    assert decision.action is RotationAction.COMPLETE


def test_an_active_variant_missing_from_the_list_reinstalls_from_the_start() -> None:
    """Deleting the live variant leaves the test recoverable.

    The alternative — raising — would wedge the polling pass for every other
    test behind one that a user edited mid-flight.
    """
    decision = decide(_state(active=uuid.uuid4(), impressions=50_000))

    assert decision.action is RotationAction.INSTALL
    assert decision.variant_id == VARIANTS[0]


@pytest.mark.parametrize("budget", [100, 500, 10_000, 250_000])
def test_the_impression_budget_is_configurable_per_test(budget: int) -> None:
    """10 000 is the default, not a constant baked into the decision."""
    assert decide(_state(active=VARIANTS[0], impressions=budget, budget=budget)).action is (
        RotationAction.ADVANCE
    )
    assert (
        decide(_state(active=VARIANTS[0], impressions=budget - 1, budget=budget)).action
        is RotationAction.HOLD
    )
