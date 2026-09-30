"""When a polling pass swaps the photo, wraps the circle, or pauses the test.

Split from ``test_runner.py``, which is about what a pass credits and in what
order. These are about what it does next, and the rule they pin is the one a
seller was promised: the rotation goes round and round while the advertising
runs, and when it stops the photo that is up serves out its turn and the test
waits — it does not end. Ending one is the seller's decision.

The distinction that matters most here is PAUSED versus UNKNOWN. «Nothing is
serving» and «WB did not answer» look identical at the call site and mean
opposite things: one stops the rotation, the other is a blip.
"""

from __future__ import annotations

from src.modules.ab_tests.models import AbTestStatus, TriggerMode
from src.modules.ab_tests.services.budget import AdsState
from src.modules.ab_tests.services.collection import Counters
from src.modules.ab_tests.services.rotation import RotationAction
from src.modules.ab_tests.services.runner import Snapshot
from tests.support.ab_tests_runner import (
    DAY,
    T0,
    T1,
    FakeExposures,
    FakeInstaller,
    FakeSnapshots,
    FakeTests,
    FakeWindows,
    build_runner,
    make_variant,
    one_campaign,
    running_test,
)


async def test_a_spent_budget_pauses_at_the_swap_rather_than_ending_the_test() -> None:
    """The trigger is met, so a swap is due — and it becomes a pause instead.

    Nothing the rotation can see is a reason to finish a test: a campaign that
    emptied overnight is topped up in the morning. Completing here made a
    routine event permanent and cost the seller every measurement the test had
    gathered.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        ads=AdsState.PAUSED,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.paused is True
    assert tests.status_writes == [AbTestStatus.PAUSED]
    assert test.status == AbTestStatus.PAUSED.value
    # The photo that was up stays up: pausing is not taking the card down.
    assert installer.installed == []


async def test_a_time_slot_ending_with_no_advertising_pauses_instead_of_swapping() -> None:
    """«По времени» is not a way round the advertising.

    The clock would move the photo whatever the traffic, so this mode is the one
    that could deal photos through dead air — every turn recorded as zero. It
    pauses at the swap exactly as the impression mode does.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first, mode=TriggerMode.TIME, slot_minutes=5)
    installer = FakeInstaller()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=0)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        ads=AdsState.PAUSED,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.paused is True
    assert tests.status_writes == [AbTestStatus.PAUSED]
    assert installer.installed == []


async def test_a_blip_wb_could_not_answer_does_not_stop_the_rotation() -> None:
    """UNKNOWN is not PAUSED, and the difference is a stalled experiment.

    WB being unreachable is not evidence that nothing is serving. Treating the
    two the same would stop live tests for a reason the seller would go hunting
    for in a campaign that is working fine.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        ads=AdsState.UNKNOWN,
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert outcome.action is RotationAction.ADVANCE
    assert outcome.paused is False
    assert tests.status_writes == []
    assert installer.installed == [(test.nm_id, second.id)]


async def test_the_rotation_wraps_and_counts_a_new_round() -> None:
    """Past the last photo the circle closes, and the lap counter moves once.

    The round advances when the leading photo comes back up — not by dividing
    turns by photos, which stops being true the moment one is excluded.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=second)
    exposures = FakeExposures(active_since=T0, round_number=1)
    installer = FakeInstaller()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=exposures,
        installer=installer,
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert installer.installed == [(test.nm_id, first.id)]
    assert exposures.rounds == [2]


async def test_a_mid_round_swap_stays_in_the_same_round() -> None:
    """Only coming back to the leader starts a new lap."""
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    exposures = FakeExposures(active_since=T0, round_number=3)
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=exposures,
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert exposures.rounds == [3]


async def test_a_switched_off_campaign_pauses_the_test_and_drops_its_baseline() -> None:
    """The seller paused their advertising; the test waits rather than finishes.

    Two things have to happen together. The status becomes PAUSED — not
    COMPLETED, because the money is still there and the campaign can come back.
    And the counter baseline is dropped, because WB's counters are cumulative
    since midnight: a baseline left behind over a three-hour pause makes the
    first window after it three hours wide and credits the lot to whichever
    photo happens to be up when the campaign returns.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    snapshots = FakeSnapshots(
        Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
    )
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=snapshots,
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        ads=AdsState.PAUSED,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.action is RotationAction.HOLD
    assert tests.status_writes == [AbTestStatus.PAUSED]
    assert test.paused_by_ads is True
    assert snapshots.cleared is True
    # The photo that was up stays up. Pausing is not taking the card down.
    assert installer.installed == []
