"""Unit tests for the rotation decision (ab_tests/services/rotation.py).

The rotation is the whole product: a photo stays on the card until its turn is
over, then the next one goes up. What ends a turn is a bound on the audience, a
bound on the clock, or both at once — and most of this file is about which of
them each mode reads. A test configured by impressions must ignore the clock
entirely and one configured by time must ignore the counter, while "Impressions
or time" ends the turn at whichever arrives first.
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
    excluded: bool = False,
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
        active_is_excluded=excluded,
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
    started later. Measured 2026-09-07, consecutive passes drift by up to
    ~14 ms. Losing that coin flip made an observed five-minute slot run
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


def test_a_time_test_starts_a_new_lap_after_its_last_slot() -> None:
    """Time mode closes the circle the same way impressions mode does."""
    decision = decide(
        _state(
            active=VARIANTS[-1],
            mode=TriggerMode.TIME,
            active_since=NOW - timedelta(minutes=120),
        )
    )

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[0]


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


def test_the_last_variant_wraps_to_the_first_and_starts_another_lap() -> None:
    """The rotation is a circle: past the last photo comes the first again.

    Nothing here ends a test, and that is the point of the split. One lap of a
    ten-photo test is ten slots, and whether ten slots is enough traffic to tell
    the photos apart has nothing to do with the number ten — the advertising
    budget decides, and the runner asks about it. See services/budget.py.
    """
    decision = decide(_state(active=VARIANTS[-1], impressions=10_000))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[0]


def test_the_decision_is_only_ever_about_which_photo_is_next() -> None:
    """A guard on the split, not a restatement of the case above.

    Whether a test should still be turning is a question about the advertising,
    which this function cannot see. If it ever learns to stop one there will be
    two places that can, and they will disagree.
    """
    states = [
        _state(active=VARIANTS[0], impressions=10_000),
        _state(active=VARIANTS[-1], impressions=10_000),
        _state(active=VARIANTS[0], impressions=0),
        _state(active=None),
        _state(active=None, variants=[]),
        _state(active=uuid.uuid4(), impressions=10_000),
    ]

    assert all(
        decide(state).action
        in {RotationAction.INSTALL, RotationAction.ADVANCE, RotationAction.HOLD}
        for state in states
    )


def test_a_test_with_no_variants_cannot_start() -> None:
    """An empty test is a configuration error, not a rotation that completes."""
    decision = decide(_state(active=None, variants=[]))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id is None


def test_a_single_variant_test_reinstalls_the_only_photo_it_has() -> None:
    """One photo is a valid, if pointless, test: the circle is one step long.

    It ends when the budget does, like any other — not by running out of photos.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=10_000, variants=VARIANTS[:1]))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[0]


def test_an_active_variant_missing_from_the_list_moves_on_immediately() -> None:
    """The live photo left the rotation — deleted, or excluded while it was up.

    Both mean the same thing to the seller who just did it: take it off the
    card. Its slot is not waited out. The alternative — raising — would wedge
    the polling pass for every other test behind one that was edited mid-flight.
    """
    decision = decide(_state(active=uuid.uuid4(), impressions=50_000))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[0]


def test_excluding_the_live_photo_takes_it_off_without_finishing_its_slot() -> None:
    """Removing a photo from rotation during its own turn means now, not in 18 minutes."""
    assert decide(_state(active=VARIANTS[0], impressions=0)).action is RotationAction.HOLD

    excluded = decide(_state(active=VARIANTS[0], impressions=0, excluded=True))

    assert excluded.action is RotationAction.ADVANCE
    assert excluded.variant_id == VARIANTS[1]


def test_an_excluded_photo_is_simply_not_dealt() -> None:
    """The caller filters them out; the circle closes over what is left."""
    remaining = [VARIANTS[0], VARIANTS[2]]

    decision = decide(_state(active=VARIANTS[2], impressions=10_000, variants=remaining))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[0]


def test_a_test_whose_every_photo_is_excluded_holds_rather_than_rotating() -> None:
    """Nothing left to deal is the same state as nothing ever uploaded."""
    decision = decide(_state(active=VARIANTS[0], impressions=10_000, variants=[]))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id is None


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


# --------------------------------------------------------------------------- #
# Trigger: either — whichever comes first
# --------------------------------------------------------------------------- #


def test_either_mode_advances_on_the_budget_before_the_slot_is_up() -> None:
    """Traffic arrived fast, so the audience bound is the one that fires.

    The point of the mode: a photo that has had its 10 000 chances does not go
    on standing there for the rest of the hour.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.EITHER,
            impressions=10_000,
            active_since=NOW - timedelta(minutes=5),
        )
    )

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_either_mode_advances_on_the_slot_before_the_budget_is_met() -> None:
    """Traffic dried up, so the clock is the one that fires.

    This is the failure the mode exists for: on a budget alone the photo would
    sit on the card for days waiting for impressions that are not coming.
    """
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.EITHER,
            impressions=12,
            active_since=NOW - timedelta(minutes=SLOT_MINUTES),
        )
    )

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_either_mode_holds_while_both_bounds_are_unmet() -> None:
    """Neither reached is still a hold — "or" does not mean "always"."""
    decision = decide(
        _state(
            active=VARIANTS[0],
            mode=TriggerMode.EITHER,
            impressions=9_999,
            active_since=NOW - timedelta(minutes=SLOT_MINUTES - 1),
        )
    )

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id == VARIANTS[0]
