"""The polling pass's test harness: fakes for everything around the runner.

Shared by ``testrunner.py`` (what a pass credits and in what order) and
``testrunner_stopping.py`` (when it swaps, wraps, or ends). One copy, because
two copies of a fake exposure log is two definitions of what an exposure is.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant, TriggerMode
from src.modules.ab_tests.services.budget import AdsState
from src.modules.ab_tests.services.collection import CampaignDays, Counters
from src.modules.ab_tests.services.runner import RotationRunner, Snapshot

NM_ID = 995716075
BUDGET = 10_000
DAY = date(2026, 9, 4)
#: The campaign every single-campaign case in these tests runs under. A real
#: id rather than 1: the legacy «before the split» rows are campaign 0, and a
#: test that accidentally used it would be asserting about the wrong case.
CAMPAIGN = 97455930
#: A second one, for the cases that are about two campaigns on one card.
OTHER_CAMPAIGN = 97730900


T0 = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 4, 12, 5, tzinfo=UTC)


def one_campaign(by_day: dict[date, Counters], campaign_id: int = CAMPAIGN) -> CampaignDays:
    """A whole reading that came from a single campaign.

    Most cases here are not about which campaign paid — they are about the
    order of the pass — and this keeps them saying so in one word.
    """
    return {campaign_id: by_day}


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
    """One recorded interval of one campaign."""

    variant_id: uuid.UUID
    campaign_id: int
    window_start: datetime
    window_end: datetime
    counters: Counters


class FakeWindows:
    """In-memory interval store.

    Impressions are summed out of the recorded rows rather than kept in a
    counter beside them, so ``since`` behaves here exactly as the SQL does: a
    photo's second turn starts at zero, which is the rule that keeps a rotation
    from collapsing into a swap every pass.
    """

    def __init__(self) -> None:
        self.rows: list[AppendedWindow] = []

    async def append(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        campaign_id: int,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None:
        self.rows.append(
            AppendedWindow(variant_id, campaign_id, window_start, window_end, counters)
        )

    async def impressions_for_variant(
        self, *, variant_id: uuid.UUID, since: datetime | None = None
    ) -> int:
        return sum(
            row.counters.views
            for row in self.rows
            if row.variant_id == variant_id and (since is None or row.window_start >= since)
        )


class FakeSnapshots:
    """In-memory baseline."""

    def __init__(self, snapshot: Snapshot | None = None) -> None:
        self.snapshot = snapshot
        self.cleared = False
        self.saves: list[datetime] = []

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None:
        return self.snapshot

    async def save(
        self, *, test_id: uuid.UUID, by_campaign: CampaignDays, captured_at: datetime
    ) -> None:
        self.saves.append(captured_at)
        self.snapshot = Snapshot(captured_at=captured_at, by_campaign=by_campaign)

    async def clear(self, *, test_id: uuid.UUID) -> None:
        self.snapshot = None
        self.cleared = True


class FakeExposures:
    """In-memory exposure log."""

    def __init__(
        self,
        active_since: datetime | None = None,
        *,
        round_number: int = 0,
        published_at: datetime | None = None,
    ) -> None:
        self._active_since = active_since
        self._round = round_number
        self._published_at = published_at
        self.opened: list[uuid.UUID] = []
        self.rounds: list[int] = []
        self.closed: list[datetime] = []
        self.witnessed: list[datetime | None] = []

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None:
        return self._active_since

    async def published_at_of_open(self, *, test_id: uuid.UUID) -> datetime | None:
        return self._published_at

    async def current_round(self, *, test_id: uuid.UUID) -> int:
        return self._round

    async def open(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        activated_at: datetime,
        round_number: int = 1,
        published_at: datetime | None = None,
    ) -> object:
        self.opened.append(variant_id)
        self.rounds.append(round_number)
        self.witnessed.append(published_at)
        self._round = round_number
        self._active_since = activated_at
        self._published_at = published_at
        return None

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed.append(deactivated_at)


class FakeTests:
    """Records the lifecycle writes the runner makes."""

    def __init__(self) -> None:
        self.active_writes: list[uuid.UUID | None] = []
        self.status_writes: list[AbTestStatus] = []
        self.photo_conflicts: list[datetime] = []

    async def pause_for_ads(self, *, test: AbTest, at: datetime) -> None:
        test.status = AbTestStatus.PAUSED.value
        test.paused_by_ads = True
        test.stopped_at = at
        self.status_writes.append(AbTestStatus.PAUSED)

    async def pause_for_photo_conflict(self, *, test: AbTest, at: datetime) -> None:
        test.status = AbTestStatus.PAUSED.value
        test.paused_by_ads = False
        test.photo_conflict_at = at
        test.stopped_at = at
        self.photo_conflicts.append(at)
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
    reading: CampaignDays,
    windows: FakeWindows,
    snapshots: FakeSnapshots,
    exposures: FakeExposures,
    installer: FakeInstaller,
    tests: FakeTests,
    ads: AdsState = AdsState.SERVING,
    live_photo: datetime | None = None,
    confirmed_photo: datetime | None = None,
    recorded: list[list[int]] | None = None,
) -> RotationRunner:
    """A runner wired entirely to fakes.

    ``recorded``, when passed, collects the campaign ids each pass names to the
    register — the list the page later labels.

    ``ads`` defaults to a campaign that is serving, because that is the state a
    test spends almost all of its life in; the cases about it stopping say so.

    The two photo arguments default to ``None``, which is the witness saying «I
    cannot tell» — the state in which the guard stands aside. That is the right
    default for every case that is not ABOUT the guard: those cases would
    otherwise all have to describe a storefront they do not care about.
    """

    async def _read(nm_id: int, days: object) -> CampaignDays:
        return reading

    seen: list[list[int]] = recorded if recorded is not None else []

    async def _remember(campaign_ids: Sequence[int], at: datetime) -> None:
        seen.append(list(campaign_ids))

    async def _ads(nm_id: int) -> AdsState:
        return ads

    async def _photo(nm_id: int) -> datetime | None:
        return live_photo

    async def _confirm(nm_id: int, was: datetime | None) -> datetime | None:
        return confirmed_photo

    return RotationRunner(
        tests=tests,
        exposures=exposures,
        windows=windows,
        snapshots=snapshots,
        installer=installer,
        read_counters=_read,
        read_ads=_ads,
        read_photo=_photo,
        confirm_install=_confirm,
        remember_campaigns=_remember,
    )


__all__ = [
    "BUDGET",
    "CAMPAIGN",
    "DAY",
    "NM_ID",
    "OTHER_CAMPAIGN",
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
    "one_campaign",
    "running_test",
]
