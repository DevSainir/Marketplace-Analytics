"""Unit tests for pausing and cancelling a test by hand (services/catalog.py).

Only a start used to be guarded, by the launcher. A pause was accepted from any
status, and a start from that pause then passed the launcher's check — so a
cancelled test could be paused, started, and put back to rewriting the live WB
card. A cancel re-stamped the finish of a test that had already finished. Every
refused transition below is one the route answers with 409, and none of them may
write anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.core.exceptions import ConflictError
from src.core.ids import uuid7
from src.modules.ab_tests.models import (
    DEFAULT_IMPRESSION_BUDGET,
    DEFAULT_SLOT_MINUTES,
    AbTest,
    AbTestStatus,
    TriggerMode,
)
from src.modules.ab_tests.services.catalog import AbTestCatalogService

NM_FLOWER_DRESS = 995716075
CREATED = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def _test(status: AbTestStatus) -> AbTest:
    """A test standing in the given status, with no photos."""
    test = AbTest(
        id=uuid7(),
        workspace_id=uuid7(),
        nm_id=NM_FLOWER_DRESS,
        vendor_code="DRESS-01",
        name="Photo test",
        status=status.value,
        trigger_mode=TriggerMode.IMPRESSIONS.value,
        impression_budget=DEFAULT_IMPRESSION_BUDGET,
        slot_minutes=DEFAULT_SLOT_MINUTES,
        created_at=CREATED,
    )
    test.variants = []
    return test


class _FakeTests:
    """Serves one test and records every status written to it."""

    def __init__(self, test: AbTest) -> None:
        self._test = test
        self.statuses: list[str] = []
        self.stopped: list[datetime | None] = []

    async def get(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest | None:
        if (workspace_id, test_id) != (self._test.workspace_id, self._test.id):
            return None
        return self._test

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
        self.statuses.append(status.value)
        self.stopped.append(stopped_at)


class _FakeExposures:
    """Records exposures closed by a cancel."""

    def __init__(self) -> None:
        self.closed: list[uuid.UUID] = []
        self.closed_at: list[datetime] = []

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed.append(test_id)
        self.closed_at.append(deactivated_at)


class _FakeSnapshots:
    """Records counter baselines dropped by a pause."""

    def __init__(self) -> None:
        self.cleared: list[uuid.UUID] = []

    async def clear(self, *, test_id: uuid.UUID) -> None:
        self.cleared.append(test_id)


class _NoInstaller:
    """A pause or cancel never puts a photo on the card."""

    async def install(self, **_: object) -> None:
        raise AssertionError("a pause or cancel must not call WB")


def _service(
    test: AbTest,
) -> tuple[AbTestCatalogService, _FakeTests, _FakeExposures, _FakeSnapshots]:
    """Assemble the service over fakes, returning what it writes through."""
    tests, exposures, snapshots = _FakeTests(test), _FakeExposures(), _FakeSnapshots()
    service = AbTestCatalogService(
        tests=tests,  # type: ignore[arg-type]
        variants=None,  # type: ignore[arg-type]
        exposures=exposures,  # type: ignore[arg-type]
        stats=None,  # type: ignore[arg-type]
        snapshots=snapshots,  # type: ignore[arg-type]
        campaigns=None,  # type: ignore[arg-type]
        media_store=None,  # type: ignore[arg-type]
    )
    return service, tests, exposures, snapshots


@pytest.mark.parametrize(
    "current",
    [
        pytest.param(AbTestStatus.DRAFT, id="draft"),
        pytest.param(AbTestStatus.PAUSED, id="already paused"),
        pytest.param(AbTestStatus.COMPLETED, id="completed"),
        pytest.param(AbTestStatus.CANCELLED, id="cancelled"),
    ],
)
async def test_only_a_running_test_can_be_paused(current: AbTestStatus) -> None:
    """A pause from anything but running is refused and writes nothing."""
    test = _test(current)
    service, tests, _, snapshots = _service(test)

    with pytest.raises(ConflictError):
        await service.set_status(
            workspace_id=test.workspace_id,
            test_id=test.id,
            status=AbTestStatus.PAUSED.value,
            installer=_NoInstaller(),  # type: ignore[arg-type]
        )

    assert test.status == current.value
    assert tests.statuses == []
    assert snapshots.cleared == []


@pytest.mark.parametrize(
    ("current", "reason"),
    [
        pytest.param(AbTestStatus.DRAFT, "delete the draft", id="draft"),
        pytest.param(AbTestStatus.COMPLETED, "already finished", id="completed"),
        pytest.param(AbTestStatus.CANCELLED, "already finished", id="cancelled"),
    ],
)
async def test_only_a_started_unfinished_test_can_be_cancelled(
    current: AbTestStatus, reason: str
) -> None:
    """A cancel of a draft or a finished test is refused and re-stamps nothing."""
    test = _test(current)
    service, tests, exposures, _ = _service(test)

    with pytest.raises(ConflictError, match=reason):
        await service.set_status(
            workspace_id=test.workspace_id,
            test_id=test.id,
            status=AbTestStatus.CANCELLED.value,
            installer=_NoInstaller(),  # type: ignore[arg-type]
        )

    assert test.status == current.value
    assert tests.statuses == []
    assert exposures.closed == []


async def test_a_cancelled_test_cannot_be_revived_through_a_pause() -> None:
    """The route to a second start is closed at the pause, before the launcher."""
    test = _test(AbTestStatus.CANCELLED)
    service, _, _, _ = _service(test)

    with pytest.raises(ConflictError, match="already finished"):
        await service.set_status(
            workspace_id=test.workspace_id,
            test_id=test.id,
            status=AbTestStatus.PAUSED.value,
            installer=_NoInstaller(),  # type: ignore[arg-type]
        )

    assert test.status == AbTestStatus.CANCELLED.value


async def test_a_running_test_can_be_paused() -> None:
    """The one allowed pause still drops the baseline and records the status."""
    test = _test(AbTestStatus.RUNNING)
    service, tests, _, snapshots = _service(test)

    row = await service.set_status(
        workspace_id=test.workspace_id,
        test_id=test.id,
        status=AbTestStatus.PAUSED.value,
        installer=_NoInstaller(),  # type: ignore[arg-type]
    )

    assert row.status == AbTestStatus.PAUSED.value
    assert tests.statuses == [AbTestStatus.PAUSED.value]
    assert snapshots.cleared == [test.id]


@pytest.mark.parametrize(
    "current",
    [
        pytest.param(AbTestStatus.RUNNING, id="running"),
        pytest.param(AbTestStatus.PAUSED, id="paused"),
    ],
)
async def test_a_running_or_paused_test_can_be_cancelled(current: AbTestStatus) -> None:
    """The "Finish" button works from both states the page offers it in."""
    test = _test(current)
    service, tests, exposures, _ = _service(test)

    row = await service.set_status(
        workspace_id=test.workspace_id,
        test_id=test.id,
        status=AbTestStatus.CANCELLED.value,
        installer=_NoInstaller(),  # type: ignore[arg-type]
    )

    assert row.status == AbTestStatus.CANCELLED.value
    assert tests.statuses == [AbTestStatus.CANCELLED.value]
    assert exposures.closed == [test.id]


async def test_cancelling_a_paused_test_keeps_the_moment_it_paused() -> None:
    """The last photo stood until the pause, not until the cancel.

    Closing its turn at the cancel drew a test paused on 08.09 and cancelled on
    28.09 as one 19-day turn, and overwrote the stamp that said when it stopped.
    """
    paused_at = datetime(2026, 9, 8, 23, 30, tzinfo=UTC)
    test = _test(AbTestStatus.PAUSED)
    test.stopped_at = paused_at
    service, tests, exposures, _ = _service(test)

    await service.set_status(
        workspace_id=test.workspace_id,
        test_id=test.id,
        status=AbTestStatus.CANCELLED.value,
        installer=_NoInstaller(),  # type: ignore[arg-type]
    )

    assert exposures.closed_at == [paused_at]
    assert tests.stopped == [paused_at]
