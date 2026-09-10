"""The polling pass's test harness: fakes for everything around the runner.

Shared by ``testrunner.py`` (what a pass credits and in what order) and
``testrunner_stopping.py`` (when it swaps, wraps, or ends). One copy, because
two copies of a fake exposure log is two definitions of what an exposure is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant, TriggerMode
from src.modules.ab_tests.services.budget import AdsState
from src.modules.ab_tests.services.collection import Counters
from src.modules.ab_tests.services.runner import RotationRunner, Snapshot

NM_ID = 995716075
BUDGET = 10_000
DAY = date(2026, 9, 4)
T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 4, 12, 5, tzinfo=UTC)


def make_variant(position: int) -> AbTestVariant:
    """A persisted variant at a rotation position."""
    return AbTestVariant(
        id=uuid.uuid4(),
        position=position,
        image_path=f"v/{position}.jpg",
        image_sha256="0" * 64,
        content_type="image/jpeg",
        original_filename=f"{position}.jpg",
    )


def running_test(
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
class AppendedWindow:
    """One recorded interval."""

    variant_id: uuid.UUID
    window_start: datetime
    window_end: datetime
    counters: Counters


class FakeWindows:
    """In-memory interval store."""

    def __init__(self, impressions: dict[uuid.UUID, int] | None = None) -> None:
        self.rows: list[AppendedWindow] = []
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
        self.rows.append(AppendedWindow(variant_id, window_start, window_end, counters))
        self.impressions[variant_id] = self.impressions.get(variant_id, 0) + counters.views

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int:
        return self.impressions.get(variant_id, 0)


class FakeSnapshots:
    """In-memory baseline."""

    def __init__(self, snapshot: Snapshot | None = None) -> None:
        self.snapshot = snapshot
        self.cleared = False
        self.saves: list[datetime] = []

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None:
        return self.snapshot

    async def save(
        self, *, test_id: uuid.UUID, by_day: dict[date, Counters], captured_at: datetime
    ) -> None:
        self.saves.append(captured_at)
        self.snapshot = Snapshot(captured_at=captured_at, by_day=by_day)

    async def clear(self, *, test_id: uuid.UUID) -> None:
        self.snapshot = None
        self.cleared = True


class FakeExposures:
    """In-memory exposure log."""

    def __init__(self, active_since: datetime | None = None, *, round_number: int = 0) -> None:
        self._active_since = active_since
        self._round = round_number
        self.opened: list[uuid.UUID] = []
        self.rounds: list[int] = []
        self.closed: list[datetime] = []

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None:
        return self._active_since

    async def current_round(self, *, test_id: uuid.UUID) -> int:
        return self._round

    async def open(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        activated_at: datetime,
        round_number: int = 1,
    ) -> object:
        self.opened.append(variant_id)
        self.rounds.append(round_number)
        self._round = round_number
        self._active_since = activated_at
        return None

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed.append(deactivated_at)


class FakeTests:
    """Records the lifecycle writes the runner makes."""

    def __init__(self) -> None:
        self.active_writes: list[uuid.UUID | None] = []
        self.status_writes: list[AbTestStatus] = []

    async def pause_for_ads(self, *, test: AbTest, at: datetime) -> None:
        test.status = AbTestStatus.PAUSED.value
        test.paused_by_ads = True
        test.stopped_at = at
        self.status_writes.append(AbTestStatus.PAUSED)

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
        stopped_at: datetime | None = None,
    ) -> None:
        test.status = status.value
        self.status_writes.append(status)


class FakeInstaller:
    """Records which variant would be pushed to WB."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.installed: list[tuple[int, uuid.UUID]] = []
        self._fail_with = fail_with

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.installed.append((nm_id, variant.id))


def build_runner(
    *,
    reading: dict[date, Counters],
    windows: FakeWindows,
    snapshots: FakeSnapshots,
    exposures: FakeExposures,
    installer: FakeInstaller,
    tests: FakeTests,
    ads: AdsState = AdsState.SERVING,
) -> RotationRunner:
    """A runner wired entirely to fakes.

    ``ads`` defaults to a campaign that is serving, because that is the state a
    test spends almost all of its life in; the cases about it stopping say so.
    """

    async def _read(nm_id: int, days: object) -> dict[date, Counters]:
        return reading

    async def _ads(nm_id: int) -> AdsState:
        return ads

    return RotationRunner(
        tests=tests,
        exposures=exposures,
        windows=windows,
        snapshots=snapshots,
        installer=installer,
        read_counters=_read,
        read_ads=_ads,
    )


__all__ = [
    "BUDGET",
    "DAY",
    "NM_ID",
    "T0",
    "T1",
    "AppendedWindow",
    "FakeExposures",
    "FakeInstaller",
    "FakeSnapshots",
    "FakeTests",
    "FakeWindows",
    "build_runner",
    "make_variant",
    "running_test",
]
