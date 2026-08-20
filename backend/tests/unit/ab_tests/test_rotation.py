"""Unit tests for the rotation decision (ab_tests/services/rotation.py).

The rotation is the whole product: a photo stays on the card until it has been
shown ``impression_budget`` times, then the next one goes up. Everything else in
the module exists to feed or record that decision, so it is kept as a pure
function of counted impressions and is pinned here rather than through the DB.

Impressions are **advertising** impressions. WB exposes no organic ones through
any API (verified live — see the ``wildberries-api`` skill), so a test with no
running campaign accumulates nothing and correctly never advances.
"""

from __future__ import annotations

import uuid

import pytest

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


def _state(
    *,
    active: uuid.UUID | None,
    impressions: int,
    variants: list[uuid.UUID] | None = None,
    budget: int = BUDGET,
) -> RotationState:
    """A rotation state with the module's default budget."""
    return RotationState(
        active_variant_id=active,
        variant_ids=variants if variants is not None else VARIANTS,
        impressions_for_active=impressions,
        impression_budget=budget,
    )


def test_the_photo_changes_once_the_budget_is_reached() -> None:
    """At 10 000 impressions the next variant is installed.

    This is the product's central promise: the picture actually rotates, and it
    rotates on impressions rather than on elapsed days.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=10_000))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_one_impression_short_of_the_budget_holds() -> None:
    """9 999 impressions is not 10 000 — the photo stays put.

    The boundary matters because advertising days arrive in lumps: a variant can
    sit just under budget for a day and must not be rotated early.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=9_999))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id == VARIANTS[0]


def test_overshooting_the_budget_still_advances_exactly_one_step() -> None:
    """A day that lands 40 000 impressions at once advances by one, not four.

    WB reports whole days, so a variant routinely blows past its budget inside
    one report. Skipping variants proportionally would leave photos untested.
    """
    decision = decide(_state(active=VARIANTS[0], impressions=41_337))

    assert decision.action is RotationAction.ADVANCE
    assert decision.variant_id == VARIANTS[1]


def test_a_test_with_no_active_photo_installs_the_first_variant() -> None:
    """Starting a test puts variant 1 on the card."""
    decision = decide(_state(active=None, impressions=0))

    assert decision.action is RotationAction.INSTALL
    assert decision.variant_id == VARIANTS[0]


def test_the_last_variant_completes_the_test_instead_of_wrapping() -> None:
    """After the final photo meets its budget the test is finished.

    Wrapping around silently would keep rewriting the seller's card forever;
    a second round has to be started deliberately.
    """
    decision = decide(_state(active=VARIANTS[-1], impressions=10_000))

    assert decision.action is RotationAction.COMPLETE
    assert decision.variant_id is None


def test_a_test_with_no_variants_cannot_start() -> None:
    """An empty test is a configuration error, not a rotation that completes."""
    decision = decide(_state(active=None, impressions=0, variants=[]))

    assert decision.action is RotationAction.HOLD
    assert decision.variant_id is None


def test_a_single_variant_test_completes_at_its_budget() -> None:
    """One photo is a valid, if pointless, test — it must still terminate."""
    decision = decide(_state(active=VARIANTS[0], impressions=10_000, variants=VARIANTS[:1]))

    assert decision.action is RotationAction.COMPLETE


def test_an_active_variant_missing_from_the_list_reinstalls_from_the_start() -> None:
    """Deleting the live variant leaves the test recoverable.

    The alternative — raising — would wedge the daily pass for every other test
    behind one that a user edited mid-flight.
    """
    decision = decide(_state(active=uuid.uuid4(), impressions=50_000))

    assert decision.action is RotationAction.INSTALL
    assert decision.variant_id == VARIANTS[0]


@pytest.mark.parametrize("budget", [1, 500, 10_000, 250_000])
def test_the_budget_is_configurable_per_test(budget: int) -> None:
    """10 000 is the default, not a constant baked into the decision."""
    assert decide(_state(active=VARIANTS[0], impressions=budget, budget=budget)).action is (
        RotationAction.ADVANCE
    )
    assert decide(_state(active=VARIANTS[0], impressions=budget - 1, budget=budget)).action is (
        RotationAction.HOLD
    )
