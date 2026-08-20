"""The rotation decision: which photo should be on the card right now.

Kept as a pure function of "how many impressions has the live photo gathered"
so the rule can be pinned by fast tests and read without following a session
through three layers. Everything stateful — reading the counts, writing the
exposure row, calling WB — lives in :mod:`.services.tests` around this.

Why impressions and not days: WB's advertising volume swings by an order of
magnitude between days, so a fixed 7-day slot gives one photo ten times the
audience of another and compares nothing. A fixed impression budget makes the
arms comparable, which is the only reason to run the rotation at all.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass


class RotationAction(enum.StrEnum):
    """What the daily pass should do with a test."""

    #: No photo is live yet — put the first variant on the card.
    INSTALL = "install"
    #: The live photo met its budget — install the next one.
    ADVANCE = "advance"
    #: Nothing to do; the live photo is still gathering impressions.
    HOLD = "hold"
    #: The last variant met its budget — the test is over.
    COMPLETE = "complete"


@dataclass(frozen=True)
class RotationState:
    """Everything the decision needs about one test.

    Attributes:
        active_variant_id: The photo currently on the card, if any.
        variant_ids: Every variant in rotation order (``position`` ascending).
        impressions_for_active: Ad impressions attributed to the live photo
            across all of its exposures — full days only.
        impression_budget: What one photo must gather before the next goes up.
    """

    active_variant_id: uuid.UUID | None
    variant_ids: list[uuid.UUID]
    impressions_for_active: int
    impression_budget: int


@dataclass(frozen=True)
class RotationDecision:
    """The action to take, and the variant it applies to."""

    action: RotationAction
    variant_id: uuid.UUID | None


def decide(state: RotationState) -> RotationDecision:
    """Decide whether the card's photo should change.

    Args:
        state: The test's variants, live photo and accumulated impressions.

    Returns:
        The action for the daily pass. ``HOLD`` with no variant means the test
        is not runnable (nothing uploaded) rather than merely waiting.
    """
    if not state.variant_ids:
        return RotationDecision(RotationAction.HOLD, None)

    if state.active_variant_id is None:
        return RotationDecision(RotationAction.INSTALL, state.variant_ids[0])

    try:
        position = state.variant_ids.index(state.active_variant_id)
    except ValueError:
        # The live variant was deleted mid-flight. Recover by restarting the
        # rotation rather than raising: one edited test must not wedge the pass
        # for every other test behind it.
        return RotationDecision(RotationAction.INSTALL, state.variant_ids[0])

    if state.impressions_for_active < state.impression_budget:
        return RotationDecision(RotationAction.HOLD, state.active_variant_id)

    # Advance exactly one step even when a single WB day overshot the budget
    # several times over — proportional skipping would leave photos untested.
    if position + 1 < len(state.variant_ids):
        return RotationDecision(RotationAction.ADVANCE, state.variant_ids[position + 1])

    return RotationDecision(RotationAction.COMPLETE, None)
