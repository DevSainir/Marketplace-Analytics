"""Unit tests for one polling pass (ab_tests/services/runner.py).

The pass is four steps in a fixed order — close the window, move the baseline,
decide, swap — and every test here is about the order rather than the arithmetic
(which lives in ``test_collection.py`` and ``test_rotation.py``).

The order is what makes several rotations a day honest: the swap happens *after*
the window closes and the baseline moves, so every interval was owned outright
by one photo and none is split between two. The old day-based pass had to throw
away the day of a swap; this one throws away nothing.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.core.exceptions import IntegrationError
from src.modules.ab_tests.models import TriggerMode
from src.modules.ab_tests.services.collection import Counters
from src.modules.ab_tests.services.rotation import RotationAction
from src.modules.ab_tests.services.runner import Snapshot
from tests.support.ab_tests_runner import (
    CAMPAIGN,
    DAY,
    NM_ID,
    OTHER_CAMPAIGN,
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


async def test_the_interval_since_the_last_poll_is_credited_to_the_live_photo() -> None:
    """A poll records the growth since the previous reading, not the total.

    The counters WB serves are cumulative since midnight; storing them raw
    would multiply every photo's traffic by the number of polls.
    """
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    windows = FakeWindows()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=7049, clicks=245, atbs=49, orders=16)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(
                captured_at=T0,
                by_campaign=one_campaign(
                    {DAY: Counters(views=6937, clicks=238, atbs=45, orders=15)}
                ),
            )
        ),
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert len(windows.rows) == 1
    row = windows.rows[0]
    assert row.variant_id == first.id
    assert (row.window_start, row.window_end) == (T0, T1)
    assert (row.counters.views, row.counters.clicks, row.counters.orders) == (112, 7, 1)


async def test_the_first_poll_seeds_the_baseline_and_records_nothing() -> None:
    """A test's very first reading produces no window.

    Without this, a test started at noon would credit its first photo with
    everything the card earned since midnight — traffic that ran under the
    seller's original picture.
    """
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    windows = FakeWindows()
    snapshots = FakeSnapshots(None)
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=6937, clicks=238)}),
        windows=windows,
        snapshots=snapshots,
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert outcome.seeded is True
    assert windows.rows == []
    assert snapshots.saves == [T1]


async def test_the_baseline_moves_before_the_photo_is_swapped() -> None:
    """The swap lands on a window boundary, so no interval spans two photos.

    This is what replaced the old rule that the day of a swap belonged to
    nobody: the baseline is already at the moment of the swap, so the next
    window starts there and the outgoing photo keeps everything up to it.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    snapshots = FakeSnapshots(
        Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
    )
    installer = FakeInstaller()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=windows,
        snapshots=snapshots,
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert windows.rows[0].variant_id == first.id
    assert windows.rows[0].window_end == T1
    assert snapshots.snapshot is not None
    assert snapshots.snapshot.captured_at == T1
    assert installer.installed == [(NM_ID, second.id)]


async def test_the_photo_changes_once_the_budget_is_reached() -> None:
    """Crossing the impression budget installs the next photo in the same pass.

    No waiting for a nightly job: the pass that observes the threshold is the
    pass that swaps, which is what makes several rotations a day possible.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    installer = FakeInstaller()
    exposures = FakeExposures(active_since=T0)
    tests = FakeTests()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_400)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=400)}))
        ),
        exposures=exposures,
        installer=installer,
        tests=tests,
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert installer.installed == [(NM_ID, second.id)]
    assert test.active_variant_id == second.id
    assert exposures.opened == [second.id]
    assert exposures.closed == [T1]


async def test_a_time_test_rotates_without_any_impressions_at_all() -> None:
    """Time mode advances on the clock even when the card served nothing.

    The reason the mode exists: on a card with advertising switched off an
    impression budget can never fire, and the test would sit on photo one
    forever.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first, mode=TriggerMode.TIME, slot_minutes=60)
    installer = FakeInstaller()
    runner = build_runner(
        reading=one_campaign({}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(Snapshot(captured_at=T0, by_campaign=one_campaign({}))),
        exposures=FakeExposures(active_since=T1 - timedelta(minutes=61)),
        installer=installer,
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert installer.installed == [(NM_ID, second.id)]


async def test_below_the_trigger_nothing_moves() -> None:
    """A quiet poll writes its window and leaves the card alone."""
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    installer = FakeInstaller()
    tests = FakeTests()
    windows = FakeWindows()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=900)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=800)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert installer.installed == []
    assert tests.status_writes == []
    assert windows.rows[0].counters.views == 100


async def test_an_empty_interval_writes_no_window() -> None:
    """A poll during which nothing happened leaves no row.

    Rows are what the result table counts days from; a stream of zero rows
    every five minutes would inflate "days measured" and bloat the table for
    nothing.
    """
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    windows = FakeWindows()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=800)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=800)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert windows.rows == []


async def test_a_failed_upload_leaves_the_test_on_the_old_photo() -> None:
    """WB refusing the swap must not advance the pointer.

    Recording the new variant anyway would attribute every following window to
    a picture that is not on the card — the metrics would describe the old
    image under the new one's name.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    tests = FakeTests()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=10_000)}),
        windows=FakeWindows(),
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(fail_with=IntegrationError("WB said no")),
        tests=tests,
    )

    with pytest.raises(IntegrationError):
        await runner.poll(test, days=[DAY], now=T1)

    assert test.active_variant_id == first.id
    assert tests.active_writes == []


async def test_a_test_with_no_live_photo_records_no_window_but_still_installs() -> None:
    """Nothing is credited while no photo is up, and the pass installs one.

    A test whose first install failed has no active variant; the traffic since
    the last poll belongs to whatever the seller's own picture was, not to a
    variant.
    """
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=None)
    windows = FakeWindows()
    installer = FakeInstaller()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=5_000)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=0)}))
        ),
        exposures=FakeExposures(active_since=None),
        installer=installer,
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert windows.rows == []
    assert installer.installed == [(NM_ID, first.id)]


async def test_each_campaign_gets_its_own_window_and_all_of_them_are_named() -> None:
    """Two campaigns on one card are two rows, not one sum.

    The live photo keeps the whole interval either way — what changes is that
    the page can afterwards ask which campaign paid for which part of it, which
    is the question a summed row can never answer again.
    """
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    windows = FakeWindows()
    named: list[list[int]] = []
    runner = build_runner(
        reading={
            CAMPAIGN: {DAY: Counters(views=6100, clicks=124)},
            OTHER_CAMPAIGN: {DAY: Counters(views=900, clicks=45)},
        },
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(
                captured_at=T0,
                by_campaign={
                    CAMPAIGN: {DAY: Counters(views=6000, clicks=120)},
                    OTHER_CAMPAIGN: {DAY: Counters(views=800, clicks=40)},
                },
            )
        ),
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(),
        tests=FakeTests(),
        recorded=named,
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert {(row.campaign_id, row.counters.views) for row in windows.rows} == {
        (CAMPAIGN, 100),
        (OTHER_CAMPAIGN, 100),
    }
    assert outcome.window_views == 200
    assert named == [[CAMPAIGN, OTHER_CAMPAIGN]]


async def test_a_campaign_that_brought_nothing_this_pass_writes_no_row() -> None:
    """A row of zeroes would make «эта РК работала в этом круге» true of one that did not."""
    first = make_variant(1)
    test = running_test([first, make_variant(2)], active=first)
    windows = FakeWindows()
    runner = build_runner(
        reading={
            CAMPAIGN: {DAY: Counters(views=6100)},
            OTHER_CAMPAIGN: {DAY: Counters(views=800)},
        },
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(
                captured_at=T0,
                by_campaign={
                    CAMPAIGN: {DAY: Counters(views=6000)},
                    OTHER_CAMPAIGN: {DAY: Counters(views=800)},
                },
            )
        ),
        exposures=FakeExposures(active_since=T0),
        installer=FakeInstaller(),
        tests=FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert [row.campaign_id for row in windows.rows] == [CAMPAIGN]


async def test_a_photo_coming_round_again_starts_its_budget_from_zero() -> None:
    """A second turn is measured from the moment it began, not from ever.

    The rotation is a circle, so every photo comes back. Counting its whole
    lifetime meant a returning photo arrived already over budget: the trigger
    fired on the first pass of every later turn and the rotation collapsed into
    a photo change every polling period. Observed on production 2026-09-19 —
    installs five minutes apart, which is the beat interval exactly.
    """
    first, second = make_variant(1), make_variant(2)
    test = running_test([first, second], active=first)
    windows = FakeWindows()
    # Its first lap, long since finished: the whole budget, and then some.
    await windows.append(
        test_id=test.id,
        variant_id=first.id,
        campaign_id=CAMPAIGN,
        window_start=T0 - timedelta(hours=6),
        window_end=T0 - timedelta(hours=6) + timedelta(minutes=5),
        counters=Counters(views=14_000),
    )
    installer = FakeInstaller()
    runner = build_runner(
        reading=one_campaign({DAY: Counters(views=520)}),
        windows=windows,
        snapshots=FakeSnapshots(
            Snapshot(captured_at=T0, by_campaign=one_campaign({DAY: Counters(views=400)}))
        ),
        # Its SECOND turn started at T0 — a minute of traffic ago.
        exposures=FakeExposures(active_since=T0),
        installer=installer,
        tests=FakeTests(),
    )

    outcome = await runner.poll(test, days=[DAY], now=T1)

    assert outcome.action is RotationAction.HOLD
    assert installer.installed == []
    assert test.active_variant_id == first.id
