"""The rotation decision: which photo should be on the card right now.

Kept as a pure function so the rule can be pinned by fast tests and read without
following a session through three layers. Everything stateful — reading the
counters, writing the exposure row, calling WB — lives in :mod:`.runner` around
this.

**The two triggers are mutually exclusive.** A test advances either on the
impressions its live photo has gathered, or on how long that photo has been up,
never on whichever comes first. Mixing them would make the arms incomparable in
the one way that matters: variants would be judged on different exposures, and
the whole reason to have a budget is that they are judged on the same one.

Which to prefer:

* **Impressions** is the statistically sound default — every photo gets the same
  number of chances, so a difference in CTR is a difference in the photo.
* **Time** trades that for predictability, and is the only mode that works at
  all on a card with no advertising running: nothing accumulates there, so an
  impression budget would never fire and the test would sit on its first photo
  forever.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.modules.ab_tests.models import TriggerMode


class RotationAction(enum.StrEnum):
    """What the polling pass should do with a test."""

    #: No photo is live yet — put the first variant on the card.
    INSTALL = "install"
    #: The live photo met its trigger — install the next one.
    ADVANCE = "advance"
    #: Nothing to do; the live photo is still gathering.
    HOLD = "hold"
    #: The last variant met its trigger — the test is over.
    COMPLETE = "complete"


@dataclass(frozen=True)
class RotationState:
    """Everything the decision needs about one test.

    Attributes:
        active_variant_id: The photo currently on the card, if any.
        variant_ids: Every variant in rotation order (``position`` ascending).
        trigger_mode: Which of the two rules applies.
        impressions_for_active: Ad impressions attributed to the live photo
            across all of its exposures. Read only in ``IMPRESSIONS`` mode.
        impression_budget: What one photo must gather before the next goes up.
        active_since: When the live photo was installed. Read only in ``TIME``
            mode; ``None`` when nothing is live.
        slot_minutes: How long one photo stays up in ``TIME`` mode.
        now: The moment the decision is being made.
    """

    active_variant_id: uuid.UUID | None
    variant_ids: list[uuid.UUID]
    trigger_mode: str
    impressions_for_active: int
    impression_budget: int
    active_since: datetime | None
    slot_minutes: int
    now: datetime


@dataclass(frozen=True)
class RotationDecision:
    """The action to take, and the variant it applies to."""

    action: RotationAction
    variant_id: uuid.UUID | None


#: How early a poll may still count a time slot as finished.
#:
#: The rotation is not a timer; a Celery pass wakes every five minutes and asks
#: whether the live photo has served its slot. Both the install and the question
#: are stamped with the pass's own start time, so for any slot that is a whole
#: number of poll periods — 5, 10, 30, 60 minutes, i.e. every value anyone
#: actually picks — the comparison comes down to which of two passes started a
#: few milliseconds later. Measured on production 2026-09-07: beat sends within
#: 0.2-5.3 ms of the minute, the queue hop adds 6.3-19.4 ms, so consecutive
#: passes drift by up to ~14 ms in either direction. Lose that coin flip and the
#: photo waits a whole extra period — a 5-minute slot ran 10 minutes, observed.
#:
#: Ten seconds is ~700x that jitter, which also leaves room for the seconds of
#: queue latency a busy worker adds during a nightly harvest. It costs at most
#: 10 s of a slot: 3 % of the five-minute minimum, 0.3 % of an hour, and never
#: anything close to the five-minute poll period, so no photo can rotate a whole
#: pass early.
SLOT_TOLERANCE: timedelta = timedelta(seconds=10)


def _trigger_met(state: RotationState) -> bool:
    """Has the live photo finished its turn?

    Args:
        state: The test's current rotation state.

    Returns:
        ``True`` when the configured trigger — and only the configured one —
        has been reached. The time trigger allows :data:`SLOT_TOLERANCE`; the
        impression budget does not, because impressions are counted, not
        clocked, and a budget that fires early would measure the arms over
        different exposures.
    """
    if state.trigger_mode == TriggerMode.TIME:
        if state.active_since is None:
            return False
        slot = timedelta(minutes=state.slot_minutes) - SLOT_TOLERANCE
        return state.now - state.active_since >= slot

    return state.impressions_for_active >= state.impression_budget


def decide(state: RotationState) -> RotationDecision:
    """Decide whether the card's photo should change.

    Args:
        state: The test's variants, live photo, counters and clock.

    Returns:
        The action for the polling pass. ``HOLD`` with no variant means the test
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

    if not _trigger_met(state):
        return RotationDecision(RotationAction.HOLD, state.active_variant_id)

    # Advance exactly one step even when a single interval overshot the budget
    # several times over — proportional skipping would leave photos untested.
    if position + 1 < len(state.variant_ids):
        return RotationDecision(RotationAction.ADVANCE, state.variant_ids[position + 1])

    return RotationDecision(RotationAction.COMPLETE, None)
