"""When the card stops showing the photo the rotation installed.

Split from the other two runner files because it is about a third question. They
ask what a pass credits and what it does next; this asks whether the pass should
be crediting anything at all — whether the picture the traffic belongs to is
still the one under test.

The case is real. On 2026-09-09 the main photo of nm 1944299862 was rewritten at
11:58:18Z, thirteen hours after the rotation's last install, and because nothing
was checking, the only reason no numbers were spoiled is that the test happened
to be paused already. On a running one the poller would have gone on crediting
window after window to a variant the card was no longer showing.

Two rules run through every case here, and they pull in opposite directions:

* A **mismatch must stop the test before anything is credited.** A window that
  closed over somebody else's photo belongs to no variant of ours, and crediting
  it and then pausing leaves exactly the wrong number behind.
* **Silence must change nothing.** An unreachable CDN, a card with no stored
  photo, an install that was never witnessed — all of them mean «cannot tell»,
  and a rotation that stopped itself on any of them would be a worse bug than
  the one the guard exists to catch.
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.modules.ab_tests.models import AbTestStatus
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

#: What the storefront said when we installed the photo that is up.
OURS = datetime(2026, 9, 4, 12, 0, 1, tzinfo=UTC)
#: What it says now, after somebody else wrote the slot.
THEIRS = datetime(2026, 9, 4, 12, 3, 30, tzinfo=UTC)


async def test_a_foreign_photo_stops_the_test_before_anything_is_credited() -> None:
    """The window is not written, the baseline is dropped, the test pauses.

    All three matter. Crediting the interval would put somebody else's traffic
    on one of our variants; keeping the baseline would hand the whole stopped
    stretch to whichever photo is up when the test restarts.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    snapshots = FakeSnapshots(
        Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
    )
    installer = FakeInstaller()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=windows,
        snapshots=snapshots,
        exposures=FakeExposures(active_since=T0, published_at=OURS),
        installer=installer,
        tests=tests,
        live_photo=THEIRS,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.photo_conflict is True
    assert outcome.action is RotationAction.HOLD
    assert outcome.window_views == 0
    assert windows.rows == []
    assert snapshots.cleared is True
    assert tests.photo_conflicts == [T1]
    assert test.status == AbTestStatus.PAUSED.value
    # The photo stays where it is: this is a stop, not a correction. Fighting
    # the seller's own edit every five minutes is the one response worse than
    # doing nothing.
    assert installer.installed == []


async def test_a_conflict_pause_is_not_an_ads_pause() -> None:
    """``paused_by_ads`` stays false, so the sweep will not resume it.

    That flag is a promise to start the test again by itself. A campaign
    switching back on is a condition that resolves; a card somebody edited is a
    decision, and honouring it is the whole point of keeping the two apart.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0, published_at=OURS),
        installer=FakeInstaller(),
        tests=FakeTests(),
        live_photo=THEIRS,
    )

    await poller.poll(test, days=[DAY], now=T1)

    assert test.paused_by_ads is False
    assert test.photo_conflict_at == T1
    assert test.stopped_at == T1


async def test_the_matching_photo_lets_the_pass_run_normally() -> None:
    """Same timestamp, so the card is still ours and nothing is interrupted."""
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0, published_at=OURS),
        installer=FakeInstaller(),
        tests=tests,
        live_photo=OURS,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.photo_conflict is False
    assert windows.rows, "the window was credited"
    assert tests.photo_conflicts == []


async def test_an_unreadable_storefront_changes_nothing() -> None:
    """The witness answering ``None`` stands the guard down.

    This is the case that decides whether the guard may run in a poller at all.
    A CDN that times out must cost the pass its check, not the seller their
    test.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0, published_at=OURS),
        installer=FakeInstaller(),
        tests=tests,
        live_photo=None,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.photo_conflict is False
    assert windows.rows, "the window was credited"
    assert test.status == AbTestStatus.RUNNING.value


async def test_an_unwitnessed_install_is_never_a_conflict() -> None:
    """With no stored timestamp there is nothing to compare, so the pass runs.

    Exposures from before the witness existed, and installs the CDN never
    confirmed, both land here. Treating a missing witness as a mismatch would
    stop every test in the system the moment this shipped.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    tests = FakeTests()
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0, published_at=None),
        installer=FakeInstaller(),
        tests=tests,
        live_photo=THEIRS,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.photo_conflict is False
    assert windows.rows, "the window was credited"
    assert tests.photo_conflicts == []


async def test_an_install_records_what_the_storefront_published() -> None:
    """The swap stores the confirmed timestamp on the new exposure.

    This is the other half of the guard: without it the next pass has nothing to
    check the card against, and the rotation is blind again one turn later.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    exposures = FakeExposures(active_since=T0, published_at=OURS)
    poller = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=exposures,
        installer=FakeInstaller(),
        tests=FakeTests(),
        live_photo=OURS,
        confirmed_photo=THEIRS,
    )

    outcome = await poller.poll(test, days=[DAY], now=T1)

    assert outcome.installed_variant_id == second.id
    assert exposures.witnessed == [THEIRS]
