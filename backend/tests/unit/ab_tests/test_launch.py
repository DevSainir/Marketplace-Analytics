"""Unit tests for starting a test (services/launch.py).

The start is where the first photo reaches the card, and the rule it has to keep
is that **every** photo the rotation deals is one WB actually served. That used
to be false on purpose: the first turn was the card's own image, captured off
WB's CDN, so the start deliberately skipped the upload. The baseline is an
upload now — the "Main photo" is a file the seller chose — and a start that still
skipped it would open the test crediting an image nobody installed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.core.exceptions import ConflictError
from src.core.ids import uuid7
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.launch import Launcher

NM_FLOWER_DRESS = 995716075
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)


def _variant(position: int, *, is_original: bool = False) -> AbTestVariant:
    """One row in the rotation."""
    return AbTestVariant(
        id=uuid7(),
        position=position,
        image_path=f"p/{position}.jpg",
        image_sha256=f"{position:064d}",
        content_type="image/jpeg",
        original_filename=f"{position}.jpg",
        is_original=is_original,
    )


def _test(*variants: AbTestVariant, status: str = AbTestStatus.DRAFT.value) -> AbTest:
    """A test carrying the given rotation."""
    test = AbTest(
        id=uuid7(), workspace_id=uuid7(), nm_id=NM_FLOWER_DRESS, name="Photo test", status=status
    )
    test.variants = list(variants)
    return test


class _FakeTests:
    """Records the two writes a start makes to the test row."""

    def __init__(self) -> None:
        self.active: list[uuid.UUID] = []
        self.statuses: list[str] = []

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID) -> None:
        test.active_variant_id = variant_id
        self.active.append(variant_id)

    async def set_status(
        self, *, test: AbTest, status: AbTestStatus, started_at: datetime | None = None
    ) -> None:
        test.status = status.value
        self.statuses.append(status.value)


class _FakeExposures:
    """Records the exposure the start opens."""

    def __init__(self) -> None:
        self.opened: list[uuid.UUID] = []
        self.rounds: list[int] = []

    async def open(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        activated_at: datetime,
        round_number: int = 1,
    ) -> None:
        self.opened.append(variant_id)
        self.rounds.append(round_number)


class _FakeInstaller:
    """Records what would have gone up on the card."""

    def __init__(self) -> None:
        self.installed: list[int] = []

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        self.installed.append(variant.position)


def _launcher() -> tuple[Launcher, _FakeTests, _FakeExposures]:
    """Assemble the launcher over fakes, returning what it writes through."""
    tests, exposures = _FakeTests(), _FakeExposures()
    return Launcher(tests=tests, exposures=exposures), tests, exposures  # type: ignore[arg-type]


async def test_the_rotation_opens_on_the_main_photo_and_installs_it() -> None:
    """The "Main photo" goes first, and it goes up — it is not assumed to be there."""
    main = _variant(0, is_original=True)
    test = _test(main, _variant(1), _variant(2))
    launcher, tests, exposures = _launcher()
    installer = _FakeInstaller()

    await launcher.launch(test=test, installer=installer, now=NOW)

    assert installer.installed == [0]
    assert exposures.opened == [main.id]
    assert tests.active == [main.id]
    assert test.status == AbTestStatus.RUNNING.value


async def test_a_test_with_no_main_photo_opens_on_its_first_upload() -> None:
    """Marking a baseline is optional; the rotation deals what it has."""
    first, second = _variant(1), _variant(2)
    test = _test(first, second)
    launcher, tests, exposures = _launcher()
    installer = _FakeInstaller()

    await launcher.launch(test=test, installer=installer, now=NOW)

    assert installer.installed == [1]
    assert exposures.opened == [first.id]
    assert tests.active == [first.id]


async def test_the_rotation_opens_on_a_photo_that_is_still_in_it() -> None:
    """An excluded first photo is skipped rather than installed and skipped."""
    excluded = _variant(0, is_original=True)
    excluded.excluded_at = NOW
    live = _variant(1)
    test = _test(excluded, live)
    launcher, _, exposures = _launcher()
    installer = _FakeInstaller()

    await launcher.launch(test=test, installer=installer, now=NOW)

    assert installer.installed == [1]
    assert exposures.opened == [live.id]


async def test_resuming_a_paused_test_does_not_reinstall() -> None:
    """The card is already showing a variant; the rotation picks up where it was."""
    live = _variant(1)
    test = _test(_variant(0, is_original=True), live, status=AbTestStatus.PAUSED.value)
    test.active_variant_id = live.id
    launcher, tests, exposures = _launcher()
    installer = _FakeInstaller()

    await launcher.launch(test=test, installer=installer, now=NOW)

    assert installer.installed == []
    assert exposures.opened == []
    assert tests.statuses == [AbTestStatus.RUNNING.value]


async def test_a_test_with_nothing_left_in_the_rotation_cannot_start() -> None:
    """A rotation with no photo to deal would hold forever, looking live."""
    only = _variant(1)
    only.excluded_at = NOW
    test = _test(only)
    launcher, _, _ = _launcher()

    with pytest.raises(ConflictError, match="at least one photo"):
        await launcher.launch(test=test, installer=_FakeInstaller(), now=NOW)


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(AbTestStatus.RUNNING.value, id="already running"),
        pytest.param(AbTestStatus.COMPLETED.value, id="finished"),
        pytest.param(AbTestStatus.CANCELLED.value, id="cancelled"),
    ],
)
async def test_a_test_in_a_terminal_state_cannot_be_started(status: str) -> None:
    """The status guards come first, so WB is never called for one."""
    test = _test(_variant(1), status=status)
    launcher, _, _ = _launcher()
    installer = _FakeInstaller()

    with pytest.raises(ConflictError):
        await launcher.launch(test=test, installer=installer, now=NOW)
    assert installer.installed == []
