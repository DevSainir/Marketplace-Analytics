"""Unit tests for finishing a test (services/finish.py).

A finish is the seller's answer to «which photo stays on the card», so the
rules pinned here are about the live storefront: the chosen photo goes up
before the test is closed, it is not re-uploaded when it is already there, it
IS re-uploaded when somebody replaced it by hand, and a WB refusal leaves the
test as it was.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.core.exceptions import ConflictError, IntegrationError, NotFoundError
from src.core.ids import uuid7
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.finish import Finisher

NM_FLOWER_DRESS = 995716075
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
WORKSPACE = uuid7()


def _variant(position: int, *, excluded: bool = False) -> AbTestVariant:
    """One photo of the test."""
    return AbTestVariant(
        id=uuid7(),
        position=position,
        image_path=f"p/{position}.jpg",
        image_sha256=f"{position:064d}",
        content_type="image/jpeg",
        original_filename=f"{position}.jpg",
        is_original=position == 0,
        excluded_at=NOW if excluded else None,
    )


def _test(
    *variants: AbTestVariant,
    status: str = AbTestStatus.PAUSED.value,
    active: AbTestVariant | None = None,
    conflict: bool = False,
) -> AbTest:
    """A test over the given photos, with the rotation's last pick on the card."""
    test = AbTest(
        id=uuid7(),
        workspace_id=WORKSPACE,
        nm_id=NM_FLOWER_DRESS,
        name="Photo test",
        status=status,
        active_variant_id=active.id if active else None,
        photo_conflict_at=NOW if conflict else None,
    )
    test.variants = list(variants)
    return test


class _FakeTests:
    """Serves one test and records what the finish writes to it."""

    def __init__(self, test: AbTest) -> None:
        self.test = test
        self.statuses: list[str] = []

    async def get(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest | None:
        if workspace_id != self.test.workspace_id or test_id != self.test.id:
            return None
        return self.test

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID) -> None:
        test.active_variant_id = variant_id

    async def set_status(
        self,
        *,
        test: AbTest,
        status: AbTestStatus,
        finished_at: datetime | None = None,
        stopped_at: datetime | None = None,
    ) -> None:
        test.status = status.value
        test.finished_at = finished_at
        test.stopped_at = stopped_at
        self.statuses.append(status.value)


class _FakeExposures:
    """Records the exposure the finish closes."""

    def __init__(self) -> None:
        self.closed_at: list[datetime] = []

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None:
        self.closed_at.append(deactivated_at)


class _FakeInstaller:
    """Records what would have gone up on the card, or refuses like WB."""

    def __init__(self, *, refuse: bool = False) -> None:
        self.installed: list[int] = []
        self.refuse = refuse

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        if self.refuse:
            raise IntegrationError("WB rejected the photo.")
        self.installed.append(variant.position)


async def _finish(
    test: AbTest, keep: AbTestVariant, installer: _FakeInstaller | None = None
) -> tuple[_FakeTests, _FakeExposures, _FakeInstaller]:
    """Finish ``test`` keeping ``keep``, returning what it wrote through."""
    tests, exposures = _FakeTests(test), _FakeExposures()
    installer = installer or _FakeInstaller()
    finisher = Finisher(tests=tests, exposures=exposures)  # type: ignore[arg-type]
    await finisher.finish(
        workspace_id=WORKSPACE,
        test_id=test.id,
        keep_variant_id=keep.id,
        installer=installer,  # type: ignore[arg-type]
        now=NOW,
    )
    return tests, exposures, installer


async def test_the_chosen_photo_goes_up_and_the_test_ends() -> None:
    """The case the dialog exists for: the best photo is not the live one."""
    main, best, live = _variant(0), _variant(1), _variant(2)
    test = _test(main, best, live, active=live)

    tests, exposures, installer = await _finish(test, best)

    assert installer.installed == [1]
    assert test.active_variant_id == best.id
    assert tests.statuses == [AbTestStatus.CANCELLED.value]
    assert test.finished_at == NOW
    assert exposures.closed_at == [NOW]


async def test_a_paused_test_ends_its_last_turn_at_the_pause() -> None:
    """The photo stood until the rotation stopped, not until the seller came back.

    Closing the turn at the finish drew a test paused on 08.09 and finished on
    28.09 as one 19-day turn beside twenty half-hour ones.
    """
    paused_at = datetime(2026, 9, 8, 23, 30, tzinfo=UTC)
    main, live = _variant(0), _variant(1)
    test = _test(main, live, active=live)
    test.stopped_at = paused_at

    _, exposures, _ = await _finish(test, main)

    assert exposures.closed_at == [paused_at]
    assert test.stopped_at == paused_at
    assert test.finished_at == NOW


async def test_keeping_the_photo_already_up_does_not_upload_it_again() -> None:
    """No spent WB request, and no fresh publish timestamp, for nothing."""
    main, live = _variant(0), _variant(1)
    test = _test(main, live, active=live)

    tests, _, installer = await _finish(test, live)

    assert installer.installed == []
    assert tests.statuses == [AbTestStatus.CANCELLED.value]


async def test_after_a_hand_edit_the_current_photo_is_put_back() -> None:
    """A photo conflict means the record says X and the card shows something else."""
    main, live = _variant(0), _variant(1)
    test = _test(main, live, active=live, conflict=True)

    _, _, installer = await _finish(test, live)

    assert installer.installed == [1]


async def test_a_photo_taken_out_of_the_rotation_can_still_be_kept() -> None:
    """Exclusion is about the rotation, and a finished test has none."""
    main, dropped = _variant(0), _variant(1, excluded=True)
    test = _test(main, dropped, active=main)

    _, _, installer = await _finish(test, dropped)

    assert installer.installed == [1]


async def test_a_refused_upload_leaves_the_test_as_it_was() -> None:
    """The seller can try again, rather than face a finished test over the wrong photo."""
    main, best = _variant(0), _variant(1)
    test = _test(main, best, active=main)

    with pytest.raises(IntegrationError):
        await _finish(test, best, _FakeInstaller(refuse=True))

    assert test.status == AbTestStatus.PAUSED.value
    assert test.active_variant_id == main.id


@pytest.mark.parametrize(
    "status",
    [
        pytest.param(AbTestStatus.DRAFT.value, id="draft"),
        pytest.param(AbTestStatus.CANCELLED.value, id="cancelled"),
        pytest.param(AbTestStatus.COMPLETED.value, id="completed"),
    ],
)
async def test_only_a_running_or_paused_test_can_be_finished(status: str) -> None:
    """A draft never touched the card; a finished test has nothing left to end."""
    main = _variant(0)
    test = _test(main, status=status, active=main)

    with pytest.raises(ConflictError):
        await _finish(test, main)


async def test_a_photo_from_another_test_is_not_found() -> None:
    """Only the test's own photos may be installed through it."""
    main, stranger = _variant(0), _variant(1)
    test = _test(main, active=main)

    with pytest.raises(NotFoundError):
        await _finish(test, stranger)


async def test_a_test_from_another_workspace_is_not_found() -> None:
    """Absent, not forbidden: a test id names a card the caller should not know."""
    main = _variant(0)
    test = _test(main, active=main)
    tests, exposures = _FakeTests(test), _FakeExposures()
    finisher = Finisher(tests=tests, exposures=exposures)  # type: ignore[arg-type]

    with pytest.raises(NotFoundError):
        await finisher.finish(
            workspace_id=uuid7(),
            test_id=test.id,
            keep_variant_id=main.id,
            installer=_FakeInstaller(),  # type: ignore[arg-type]
            now=NOW,
        )
