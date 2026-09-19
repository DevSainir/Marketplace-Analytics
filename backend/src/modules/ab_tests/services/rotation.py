"""The rotation decision: which photo should be on the card right now.

Kept as a pure function so the rule can be pinned by fast tests and read without
following a session through three layers. Everything stateful — reading the
counters, writing the exposure row, calling WB, asking whether the advertising
budget is spent — lives in :mod:`.runner` around this.

**The rotation is a circle, not a queue.** After the last photo it comes back to
the first and starts another lap, and nothing here ever ends a test. When the
advertising stops the runner PAUSES it (see :mod:`.budget`) and the sweep starts
it again when a campaign serves; finishing one for good is the seller's decision
and nobody else's. So this function only ever says which photo should be up
next — «is there a next photo» and «should this test still exist» are different
questions with different owners, and tangling them in one condition is how «the
test stopped and I don't know why» happens.

**An excluded photo is skipped, not removed.** The seller can take a photo out
mid-test; it keeps its rows and its measurements and simply stops being dealt.
The decision therefore walks the photos still in the rotation, and treats the
live photo being excluded as a reason to move on now rather than at the end of
its slot — that is what excluding it during its own turn has to mean.

**A turn ends on impressions, on the clock, or on whichever comes first.**

* **Impressions** is the statistically sound default — every photo gets the same
  number of chances, so a difference in CTR is a difference in the photo.
* **Time** trades that for predictability, and is the only mode that works at
  all on a card with no advertising running: nothing accumulates there, so an
  impression budget would never fire and the test would sit on its first photo
  forever.
* **Either** holds both bounds at once and ends the turn at the first of them.
  It is the mode for a card whose advertising is uneven: the budget still gives
  a photo its audience when traffic is there, and the slot stops it sitting on
  the card all day when traffic dries up.

**The counters are read per TURN, not per photo's lifetime.** The rotation is a
circle, so a photo comes back round; counting every impression it has ever
gathered meant that from its second lap on it started each turn already over
budget, the trigger fired on the first pass, and the whole test collapsed into a
photo change every polling period. Observed in production on 2026-09-19 — a
rotation swapping every five minutes, which is exactly the beat interval. What
the budget means is «сколько эта картинка наберёт за ход», so
``impressions_for_active`` counts the current turn only.
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


@dataclass(frozen=True)
class RotationState:
    """Everything the decision needs about one test.

    Attributes:
        active_variant_id: The photo currently on the card, if any.
        variant_ids: The variants still in the rotation, in order (``position``
            ascending). Excluded photos are absent — the caller filters them,
            because "is this photo still being dealt" is a property of the row
            and not of the decision.
        active_is_excluded: Whether the photo on the card has just been taken
            out of the rotation. It then moves on the next pass rather than
            finishing a slot nobody wants it to finish.
        trigger_mode: Which rule (or pair of rules) applies.
        impressions_for_active: Ad impressions attributed to the live photo
            **during its current turn** — see the module docstring for what
            counting its whole lifetime did instead. Read in ``IMPRESSIONS``
            and ``EITHER`` mode.
        impression_budget: What one photo must gather before the next goes up.
        active_since: When the live photo was installed. Read in ``TIME`` and
            ``EITHER`` mode; ``None`` when nothing is live.
        slot_minutes: How long one photo stays up before its turn ends.
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
    # Defaulted so every existing construction site stays valid; a test whose
    # photos are all still in the rotation is the ordinary case.
    active_is_excluded: bool = False


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
        ``True`` when a trigger the mode has in force has been reached —
        either of them in ``EITHER``, the configured one otherwise. The time
        trigger allows :data:`SLOT_TOLERANCE`; the impression budget does not,
        because impressions are counted, not clocked, and a budget that fired
        early would measure the arms over different exposures.
    """
    mode = state.trigger_mode
    if mode in {TriggerMode.TIME, TriggerMode.EITHER} and _slot_served(state):
        return True
    if mode in {TriggerMode.IMPRESSIONS, TriggerMode.EITHER}:
        return state.impressions_for_active >= state.impression_budget
    return False


def _slot_served(state: RotationState) -> bool:
    """Has the live photo been up for its whole slot?

    Args:
        state: The test's current rotation state.

    Returns:
        ``False`` when nothing is live — a photo that was never installed has
        not served anything, whatever the clock says.
    """
    if state.active_since is None:
        return False
    slot = timedelta(minutes=state.slot_minutes) - SLOT_TOLERANCE
    return state.now - state.active_since >= slot


def decide(state: RotationState) -> RotationDecision:
    """Decide which photo should be on the card next.

    The rotation is an endless circle here. Whether it should still be turning
    is a question about the advertising, which this function cannot see and the
    runner asks separately — see :mod:`.budget`.

    Args:
        state: The test's remaining variants, live photo, counters and clock.

    Returns:
        The action for the polling pass. ``HOLD`` with no variant means the test
        is not runnable — every photo is excluded, or none was ever uploaded —
        rather than merely waiting.
    """
    if not state.variant_ids:
        return RotationDecision(RotationAction.HOLD, None)

    if state.active_variant_id is None:
        return RotationDecision(RotationAction.INSTALL, state.variant_ids[0])

    try:
        position = state.variant_ids.index(state.active_variant_id)
    except ValueError:
        # The live photo is no longer in the rotation — deleted, or excluded
        # while it was up. Both mean the same thing to the seller who did it:
        # take it off now. Its slot is not waited out.
        return RotationDecision(RotationAction.ADVANCE, state.variant_ids[0])

    if state.active_is_excluded:
        return RotationDecision(
            RotationAction.ADVANCE, state.variant_ids[(position + 1) % len(state.variant_ids)]
        )

    if not _trigger_met(state):
        return RotationDecision(RotationAction.HOLD, state.active_variant_id)

    # Advance exactly one step even when a single interval overshot the budget
    # several times over — proportional skipping would leave photos untested.
    # Past the last photo the circle closes and a new lap starts.
    return RotationDecision(
        RotationAction.ADVANCE, state.variant_ids[(position + 1) % len(state.variant_ids)]
    )
