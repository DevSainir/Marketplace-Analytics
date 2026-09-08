"""When a polling pass swaps the photo, wraps the circle, or ends the test.

Split from ``test_runner.py``, which is about what a pass credits and in what
order. These are about what it does next, and the rule they pin is the one a
seller was promised: the rotation goes round and round until the advertising
paying for it is spent, and then the photo that is up serves out its turn and
nothing replaces it.

The distinction that matters most here is EXHAUSTED versus UNKNOWN. «WB said
zero» and «WB did not answer» look identical at the call site and mean opposite
things: one is the end of the experiment, the other is a blip.
"""

from __future__ import annotations

from src.modules.ab_tests.models import AbTestStatus
from src.modules.ab_tests.services.budget import BudgetState
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
    running_test,
)


async def test_a_spent_budget_ends_the_test_instead_of_swapping() -> None:
    """The promise «Запустить» makes: the photo that is up serves out its turn.

    The trigger is met here, so a swap is due — and it does not happen. Nothing
    new goes on the card, and the test is finished rather than left running with
    a photo it will never replace.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    runner = build_runner(
        reading={DAY: Counters(views=10_000)},
        windows=FakeWindows(),
        snapshots=FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        budget=BudgetState.EXHAUSTED,
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert outcome.action is RotationAction.COMPLETE
    assert tests.status_writes == [AbTestStatus.COMPLETED]
    assert installer.installed == []


async def test_a_budget_wb_could_not_be_asked_about_does_not_end_the_test() -> None:
    """UNKNOWN is not EXHAUSTED, and the difference is a whole experiment.

    WB being unreachable is not evidence the money ran out. Treating the two the
    same would end tests for a reason the seller can neither see nor fix.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    runner = build_runner(
        reading={DAY: Counters(views=10_000)},
        windows=FakeWindows(),
        snapshots=FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
        budget=BudgetState.UNKNOWN,
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert outcome.action is RotationAction.ADVANCE
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
        reading={DAY: Counters(views=10_000)},
        windows=FakeWindows(),
        snapshots=FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
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
        reading={DAY: Counters(views=10_000)},
        windows=FakeWindows(),
        snapshots=FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=exposures,
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert exposures.rounds == [3]
