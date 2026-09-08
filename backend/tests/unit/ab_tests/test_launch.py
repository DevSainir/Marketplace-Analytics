"""Unit tests for starting a test (services/launch.py).

The start is where the card's own photo joins the rotation, and where the one
saving that makes it free is claimed: the captured photo is already on the card,
so its turn must **not** cost an upload. A start that installed it anyway would
push WB's own transcoded rendition back through moderation to arrive at the
picture already there — visible to buyers, and a quality loss for nothing.
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
        id=uuid7(), workspace_id=uuid7(), nm_id=NM_FLOWER_DRESS, name="Тест фото", status=status
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


class _FakeCapture:
    """Enrols a prepared original, or nothing.

    Mirrors the real service's idempotence, because that is exactly what the
    launcher leans on: by the time a test is started its photo is normally
    already enrolled, having been captured when the test was created.
    """

    def __init__(self, original: AbTestVariant | None) -> None:
        self._original = original
        self.calls = 0

    async def enrol(self, *, test: AbTest, variants: object) -> AbTestVariant | None:
        existing = next((variant for variant in test.variants if variant.is_original), None)
        if existing is not None:
            return existing
        self.calls += 1
        if self._original is not None:
            test.variants.insert(0, self._original)
        return self._original


def _launcher() -> tuple[Launcher, _FakeTests, _FakeExposures]:
    """Assemble the launcher over fakes, returning what it writes through."""
    tests, exposures = _FakeTests(), _FakeExposures()
    return Launcher(tests=tests, variants=object(), exposures=exposures), tests, exposures  # type: ignore[arg-type]


async def test_the_rotation_opens_on_the_cards_own_photo_without_an_upload() -> None:
    """The captured original is already live, so starting installs nothing."""
    test = _test(_variant(1), _variant(2))
    original = _variant(0, is_original=True)
    launcher, tests, exposures = _launcher()
    installer, capture = _FakeInstaller(), _FakeCapture(original)

    await launcher.launch(test=test, installer=installer, capture=capture, now=NOW)

    assert installer.installed == []
    assert exposures.opened == [original.id]
    assert tests.active == [original.id]
    assert test.status == AbTestStatus.RUNNING.value


async def test_the_captured_photo_joins_the_rotation_the_response_reports() -> None:
    """It is counted immediately, not only after the next read of the test."""
    test = _test(_variant(1), _variant(2))
    original = _variant(0, is_original=True)
    launcher, _, _ = _launcher()

    await launcher.launch(
        test=test, installer=_FakeInstaller(), capture=_FakeCapture(original), now=NOW
    )

    assert [variant.position for variant in test.variants] == [0, 1, 2]


async def test_a_card_whose_photo_cannot_be_read_opens_on_the_first_upload() -> None:
    """No capture is the old behaviour, upload and all — not a refused start."""
    first, second = _variant(1), _variant(2)
    test = _test(first, second)
    launcher, tests, exposures = _launcher()
    installer = _FakeInstaller()

    await launcher.launch(test=test, installer=installer, capture=_FakeCapture(None), now=NOW)

    assert installer.installed == [1]
    assert exposures.opened == [first.id]
    assert tests.active == [first.id]


async def test_a_second_start_does_not_capture_the_photo_twice() -> None:
    """A start that died after the capture must not file a duplicate original."""
    original = _variant(0, is_original=True)
    test = _test(original, _variant(1))
    launcher, _, exposures = _launcher()
    capture = _FakeCapture(_variant(0, is_original=True))

    await launcher.launch(test=test, installer=_FakeInstaller(), capture=capture, now=NOW)

    assert capture.calls == 0
    assert exposures.opened == [original.id]


async def test_resuming_a_paused_test_neither_captures_nor_installs() -> None:
    """The card is showing a variant by then; the rotation picks up where it was."""
    original = _variant(0, is_original=True)
    live = _variant(1)
    test = _test(original, live, status=AbTestStatus.PAUSED.value)
    test.active_variant_id = live.id
    launcher, tests, exposures = _launcher()
    installer, capture = _FakeInstaller(), _FakeCapture(original)

    await launcher.launch(test=test, installer=installer, capture=capture, now=NOW)

    assert capture.calls == 0
    assert installer.installed == []
    assert exposures.opened == []
    assert tests.statuses == [AbTestStatus.RUNNING.value]


async def test_a_test_carrying_only_the_cards_own_photo_cannot_start() -> None:
    """Rotating the current image alone compares it to itself."""
    test = _test(_variant(0, is_original=True))
    launcher, _, _ = _launcher()

    with pytest.raises(ConflictError, match="хотя бы одно фото"):
        await launcher.launch(
            test=test, installer=_FakeInstaller(), capture=_FakeCapture(None), now=NOW
        )


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(AbTestStatus.RUNNING.value, id="already running"),
        pytest.param(AbTestStatus.COMPLETED.value, id="finished"),
        pytest.param(AbTestStatus.CANCELLED.value, id="cancelled"),
    ],
)
async def test_a_test_in_a_terminal_state_cannot_be_started(status: str) -> None:
    """The status guards come before the capture, so WB is never called for one."""
    test = _test(_variant(1), status=status)
    launcher, _, _ = _launcher()
    capture = _FakeCapture(None)

    with pytest.raises(ConflictError):
        await launcher.launch(test=test, installer=_FakeInstaller(), capture=capture, now=NOW)
    assert capture.calls == 0
