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

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest

from src.core.exceptions import IntegrationError
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant, TriggerMode
from src.modules.ab_tests.services.collection import Counters
from src.modules.ab_tests.services.runner import RotationRunner, Snapshot

NM_ID = 995716075
BUDGET = 10_000
DAY = date(2026, 9, 4)
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 4, 12, 5, tzinfo=UTC)


def _variant(position: int) -> AbTestVariant:
    """A persisted variant at a rotation position."""
    return AbTestVariant(
        id=uuid.uuid4(),
        position=position,
        image_path=f"v/{position}.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename=f"{position}.jpg",
    )


def _test_with(
    variants: list[AbTestVariant],
    *,
    active: AbTestVariant | None,
    mode: TriggerMode = TriggerMode.IMPRESSIONS,
    slot_minutes: int = 60,
) -> AbTest:
    """A running test over ``NM_ID`` with the given rotation."""
    test = AbTest(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        nm_id=NM_ID,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест главного фото",
        status=AbTestStatus.RUNNING.value,
        trigger_mode=mode.value,
        impression_budget=BUDGET,
        slot_minutes=slot_minutes,
        active_variant_id=active.id if active else None,
        started_at=T0,
    )
    test.variants = variants
    return test


@dataclass
class _AppendedWindow:
    """One recorded interval."""

    variant_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    counters: Counters


class _FakeWindows:
    """In-memory interval store."""

    def __init__(self, impressions: dict[uuid.UUID, int] | None = None) -> None:
        self.rows: list[_AppendedWindow] = []
        self.impressions = impressions or {}

    async def append(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None:
        self.rows.append(_AppendedWindow(variant_id, window_start, window_end, counters))
        self.impressions[variant_id] = self.impressions.get(variant_id, 0) + counters.views

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int:
        return self.impressions.get(variant_id, 0)


class _FakeSnapshots:
    """In-memory baseline."""

    def __init__(self, snapshot: Snapshot | None = None) -> None:
        self.snapshot = snapshot
        self.saves: list[datetime] = []

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None:
        return self.snapshot

    async def save(
        self, *, test_id: uuid.UUID, by_day: dict[date, Counters], captured_at: datetime
    ) -> None:
        self.saves.append(captured_at)
        self.snapshot = Snapshot(captured_at=captured_at, by_day=by_day)


class _FakeExposures:
    """In-memory exposure log."""

    def __init__(self, active_since: datetime | None = None) -> None:
        self._active_since = active_since
        self.opened: list[uuid.UUID] = []
        self.closed: list[datetime] = []

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None:
        return self._active_since

    async def open(
        self, *, test_id: uuid.UUID, variant_id: uuid.UUID, activated_at: datetime
    ) -> object:
        self.opened.append(variant_id)
        self._active_since = activated_at
        return None

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed.append(deactivated_at)


class _FakeTests:
    """Records the lifecycle writes the runner makes."""

    def __init__(self) -> None:
        self.active_writes: list[uuid.UUID | None] = []
        self.status_writes: list[AbTestStatus] = []

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID | None) -> None:
        test.active_variant_id = variant_id
        self.active_writes.append(variant_id)

    async def set_status(
        self,
        *,
        test: AbTest,
        status: AbTestStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        test.status = status.value
        self.status_writes.append(status)


class _FakeInstaller:
    """Records which variant would be pushed to WB."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.installed: list[tuple[int, uuid.UUID]] = []
        self._fail_with = fail_with

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.installed.append((nm_id, variant.id))


def _runner(
    *,
    reading: dict[date, Counters],
    windows: _FakeWindows,
    snapshots: _FakeSnapshots,
    exposures: _FakeExposures,
    installer: _FakeInstaller,
    tests: _FakeTests,
) -> RotationRunner:
    """A runner wired entirely to fakes."""

    async def _read(nm_id: int, days: object) -> dict[date, Counters]:
        return reading

    return RotationRunner(
        tests=tests,
        exposures=exposures,
        windows=windows,
        snapshots=snapshots,
        installer=installer,
        read_counters=_read,
    )


async def test_the_interval_since_the_last_poll_is_credited_to_the_live_photo() -> None:
    """A poll records the growth since the previous reading, not the total.

    The counters WB serves are cumulative since midnight; storing them raw
    would multiply every photo's traffic by the number of polls.
    """
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=first)
    windows = _FakeWindows()
    runner = _runner(
        reading={DAY: Counters(views=7049, clicks=245, atbs=49, orders=16)},
        windows=windows,
        snapshots=_FakeSnapshots(
            Snapshot(
                captured_at=T0, by_day={DAY: Counters(views=6937, clicks=238, atbs=45, orders=15)}
            )
        ),
        exposures=_FakeExposures(active_since=T0),
        installer=_FakeInstaller(),
        tests=_FakeTests(),
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
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=first)
    windows = _FakeWindows()
    snapshots = _FakeSnapshots(None)
    runner = _runner(
        reading={DAY: Counters(views=6937, clicks=238)},
        windows=windows,
        snapshots=snapshots,
        exposures=_FakeExposures(active_since=T0),
        installer=_FakeInstaller(),
        tests=_FakeTests(),
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
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    windows = _FakeWindows()
    snapshots = _FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)}))
    installer = _FakeInstaller()
    runner = _runner(
        reading={DAY: Counters(views=10_000)},
        windows=windows,
        snapshots=snapshots,
        exposures=_FakeExposures(active_since=T0),
        installer=installer,
        tests=_FakeTests(),
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
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    installer = _FakeInstaller()
    exposures = _FakeExposures(active_since=T0)
    tests = _FakeTests()
    runner = _runner(
        reading={DAY: Counters(views=10_400)},
        windows=_FakeWindows(),
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=400)})),
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
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first, mode=TriggerMode.TIME, slot_minutes=60)
    installer = _FakeInstaller()
    runner = _runner(
        reading={},
        windows=_FakeWindows(),
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={})),
        exposures=_FakeExposures(active_since=T1 - timedelta(minutes=61)),
        installer=installer,
        tests=_FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert installer.installed == [(NM_ID, second.id)]


async def test_below_the_trigger_nothing_moves() -> None:
    """A quiet poll writes its window and leaves the card alone."""
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=first)
    installer = _FakeInstaller()
    tests = _FakeTests()
    windows = _FakeWindows()
    runner = _runner(
        reading={DAY: Counters(views=900)},
        windows=windows,
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=800)})),
        exposures=_FakeExposures(active_since=T0),
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
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=first)
    windows = _FakeWindows()
    runner = _runner(
        reading={DAY: Counters(views=800)},
        windows=windows,
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=800)})),
        exposures=_FakeExposures(active_since=T0),
        installer=_FakeInstaller(),
        tests=_FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert windows.rows == []


async def test_the_last_variant_completes_the_test() -> None:
    """When the final photo meets its trigger the test stops, card unchanged."""
    only = _variant(1)
    test = _test_with([only], active=only)
    installer = _FakeInstaller()
    tests = _FakeTests()
    runner = _runner(
        reading={DAY: Counters(views=10_000)},
        windows=_FakeWindows(),
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=_FakeExposures(active_since=T0),
        installer=installer,
        tests=tests,
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert tests.status_writes == [AbTestStatus.COMPLETED]
    assert installer.installed == []


async def test_a_failed_upload_leaves_the_test_on_the_old_photo() -> None:
    """WB refusing the swap must not advance the pointer.

    Recording the new variant anyway would attribute every following window to
    a picture that is not on the card — the metrics would describe the old
    image under the new one's name.
    """
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    tests = _FakeTests()
    runner = _runner(
        reading={DAY: Counters(views=10_000)},
        windows=_FakeWindows(),
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=_FakeExposures(active_since=T0),
        installer=_FakeInstaller(fail_with=IntegrationError("WB said no")),
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
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=None)
    windows = _FakeWindows()
    installer = _FakeInstaller()
    runner = _runner(
        reading={DAY: Counters(views=5_000)},
        windows=windows,
        snapshots=_FakeSnapshots(Snapshot(captured_at=T0, by_day={DAY: Counters(views=0)})),
        exposures=_FakeExposures(active_since=None),
        installer=installer,
        tests=_FakeTests(),
    )

    await runner.poll(test, days=[DAY], now=T1)

    assert windows.rows == []
    assert installer.installed == [(NM_ID, first.id)]
