"""Unit tests for the daily rotation pass (ab_tests/services/runner.py).

This is the test the whole module exists to pass: **after 10 000 impressions the
picture on the card actually changes.** The pure decision is pinned in
``test_rotation.py``; here the decision has to reach WB, get recorded as an
exposure, and leave the test pointing at the new photo — a rotation that decides
correctly and never uploads is indistinguishable from a broken one to the user,
and worse, keeps attributing days to an image nobody saw.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.core.exceptions import IntegrationError
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.attribution import AttributedDay, ExposureWindow
from src.modules.ab_tests.services.runner import RotationRunner

NM_ID = 995716075
BUDGET = 10_000


@dataclass
class _AdDay:
    """A pre-summed advertising day, shaped like monitoring's ``AdDay``."""

    stat_date: date
    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = Decimal("0")


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


def _test_with(variants: list[AbTestVariant], *, active: AbTestVariant | None) -> AbTest:
    """A running test over ``NM_ID`` with the given rotation."""
    test = AbTest(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        nm_id=NM_ID,
        vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        name="Тест главного фото",
        status=AbTestStatus.RUNNING.value,
        impression_budget=BUDGET,
        active_variant_id=active.id if active else None,
        started_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    test.variants = variants
    return test


class _FakeInstaller:
    """Records which variant would be pushed to WB."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.installed: list[tuple[int, uuid.UUID]] = []
        self._fail_with = fail_with

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.installed.append((nm_id, variant.id))


class _FakeExposures:
    """In-memory exposure log."""

    def __init__(self, windows: list[ExposureWindow] | None = None) -> None:
        self.windows = windows or []
        self.opened: list[uuid.UUID] = []
        self.closed: list[datetime] = []

    async def windows_for_test(self, *, test_id: uuid.UUID) -> list[ExposureWindow]:
        return self.windows

    async def open(
        self, *, test_id: uuid.UUID, variant_id: uuid.UUID, activated_at: datetime
    ) -> None:
        self.opened.append(variant_id)
        self.windows.append(ExposureWindow(variant_id, activated_at, None))

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed.append(deactivated_at)
        self.windows = [
            ExposureWindow(w.variant_id, w.activated_at, w.deactivated_at or deactivated_at)
            for w in self.windows
        ]


class _FakeStats:
    """In-memory attributed days keyed by variant."""

    def __init__(self, impressions: dict[uuid.UUID, int] | None = None) -> None:
        self.impressions = impressions or {}
        self.written: list[AttributedDay] = []

    async def upsert_days(self, *, test_id: uuid.UUID, days: list[AttributedDay]) -> int:
        self.written.extend(days)
        for day in days:
            self.impressions[day.variant_id] = self.impressions.get(day.variant_id, 0) + day.views
        return len(days)

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int:
        return self.impressions.get(variant_id, 0)


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


def _runner(
    *,
    ad_days: list[_AdDay],
    exposures: _FakeExposures,
    stats: _FakeStats,
    installer: _FakeInstaller,
    tests: _FakeTests,
) -> RotationRunner:
    """A runner wired entirely to fakes."""

    async def _load(nm_id: int, date_from: date, date_to: date) -> list[_AdDay]:
        return ad_days

    return RotationRunner(
        tests=tests,
        exposures=exposures,
        stats=stats,
        installer=installer,
        load_ad_days=_load,
    )


async def test_the_photo_changes_once_the_budget_is_reached() -> None:
    """10 000 impressions on the live photo installs the next one on the card.

    The assertion is on the upload, not on the decision: the point of the pass
    is that WB is actually told to change the image.
    """
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    exposures = _FakeExposures(
        [ExposureWindow(first.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
    )
    installer = _FakeInstaller()
    tests = _FakeTests()
    runner = _runner(
        ad_days=[_AdDay(date(2026, 8, 2), views=10_000, clicks=900)],
        exposures=exposures,
        stats=_FakeStats(),
        installer=installer,
        tests=tests,
    )

    await runner.advance(test, through=date(2026, 8, 3))

    assert installer.installed == [(NM_ID, second.id)]
    assert test.active_variant_id == second.id
    assert exposures.opened == [second.id]
    assert exposures.closed  # the outgoing photo's window was closed


async def test_below_the_budget_the_photo_stays() -> None:
    """9 999 impressions changes nothing — no upload, no exposure, no writes."""
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    installer = _FakeInstaller()
    tests = _FakeTests()
    runner = _runner(
        ad_days=[_AdDay(date(2026, 8, 2), views=9_999)],
        exposures=_FakeExposures(
            [ExposureWindow(first.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
        ),
        stats=_FakeStats(),
        installer=installer,
        tests=tests,
    )

    await runner.advance(test, through=date(2026, 8, 3))

    assert installer.installed == []
    assert test.active_variant_id == first.id
    assert tests.status_writes == []


async def test_impressions_accumulate_across_days_before_the_swap() -> None:
    """The budget is a running total, not a single day's figure."""
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    runner_installer = _FakeInstaller()
    runner = _runner(
        ad_days=[
            _AdDay(date(2026, 8, 2), views=4_000),
            _AdDay(date(2026, 8, 3), views=4_000),
            _AdDay(date(2026, 8, 4), views=4_000),
        ],
        exposures=_FakeExposures(
            [ExposureWindow(first.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
        ),
        stats=_FakeStats(),
        installer=runner_installer,
        tests=_FakeTests(),
    )

    await runner.advance(test, through=date(2026, 8, 5))

    assert runner_installer.installed == [(NM_ID, second.id)]


async def test_every_metric_from_the_ad_day_is_recorded() -> None:
    """Attributed days carry all four counts and the spend, not just views.

    Views drive the rotation, so a bug that persisted only views would still
    rotate correctly while leaving the result table empty.
    """
    first = _variant(1)
    test = _test_with([first, _variant(2)], active=first)
    stats = _FakeStats()
    runner = _runner(
        ad_days=[
            _AdDay(
                date(2026, 8, 2), views=1_000, clicks=90, atbs=8, orders=3, spend=Decimal("1500")
            )
        ],
        exposures=_FakeExposures(
            [ExposureWindow(first.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
        ),
        stats=stats,
        installer=_FakeInstaller(),
        tests=_FakeTests(),
    )

    await runner.advance(test, through=date(2026, 8, 3))

    assert len(stats.written) == 1
    row = stats.written[0]
    assert (row.variant_id, row.views, row.clicks, row.atbs, row.orders) == (
        first.id,
        1_000,
        90,
        8,
        3,
    )
    assert row.spend == Decimal("1500.00")


async def test_the_last_variant_completes_the_test() -> None:
    """When the final photo meets its budget the test stops, card unchanged."""
    only = _variant(1)
    test = _test_with([only], active=only)
    installer = _FakeInstaller()
    tests = _FakeTests()
    runner = _runner(
        ad_days=[_AdDay(date(2026, 8, 2), views=10_000)],
        exposures=_FakeExposures(
            [ExposureWindow(only.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
        ),
        stats=_FakeStats(),
        installer=installer,
        tests=tests,
    )

    await runner.advance(test, through=date(2026, 8, 3))

    assert tests.status_writes == [AbTestStatus.COMPLETED]
    assert installer.installed == []


async def test_a_failed_upload_leaves_the_test_on_the_old_photo() -> None:
    """WB refusing the swap must not advance the pointer.

    Recording the new variant anyway would attribute every following day to a
    picture that is not on the card — the metrics would describe the old image
    under the new one's name.
    """
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=first)
    tests = _FakeTests()
    runner = _runner(
        ad_days=[_AdDay(date(2026, 8, 2), views=10_000)],
        exposures=_FakeExposures(
            [ExposureWindow(first.id, datetime(2026, 8, 1, 9, tzinfo=UTC), None)]
        ),
        stats=_FakeStats(),
        installer=_FakeInstaller(fail_with=IntegrationError("WB said no")),
        tests=tests,
    )

    with pytest.raises(IntegrationError):
        await runner.advance(test, through=date(2026, 8, 3))

    assert test.active_variant_id == first.id
    assert tests.active_writes == []


async def test_the_swap_day_is_not_attributed_to_either_photo() -> None:
    """A day split by a rotation is dropped rather than credited to one side."""
    first, second = _variant(1), _variant(2)
    test = _test_with([first, second], active=second)
    stats = _FakeStats()
    runner = _runner(
        ad_days=[
            _AdDay(date(2026, 8, 2), views=1_000),
            _AdDay(date(2026, 8, 3), views=1_100),  # swap happened this day
            _AdDay(date(2026, 8, 4), views=1_200),
        ],
        exposures=_FakeExposures(
            [
                ExposureWindow(
                    first.id,
                    datetime(2026, 8, 1, 9, tzinfo=UTC),
                    datetime(2026, 8, 3, 9, tzinfo=UTC),
                ),
                ExposureWindow(second.id, datetime(2026, 8, 3, 9, tzinfo=UTC), None),
            ]
        ),
        stats=stats,
        installer=_FakeInstaller(),
        tests=_FakeTests(),
    )

    await runner.advance(test, through=date(2026, 8, 5))

    assert [(row.stat_date, row.variant_id) for row in stats.written] == [
        (date(2026, 8, 2), first.id),
        (date(2026, 8, 4), second.id),
    ]
