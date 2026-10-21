"""Request-scoped operations on tests and their photos.

Everything a user does from the SPA: create a test, upload and remove photos,
start / pause / cancel it, and read the result table. The rotation itself runs
without a request (see :mod:`.runner`), and the two meet at
:class:`~src.modules.ab_tests.services.photos.VariantInstaller`.

Starting a test is its own sequence and lives in :mod:`.launch`; it runs
**synchronously** inside the request because it is a couple of WB calls, and
doing it in the background would leave the user looking at a «Запущен» test
whose card still shows the old image, with the failure buried in a worker log.
"""

# Russian, and the confusable-character check fires on ordinary Cyrillic.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.config import settings
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.modules.ab_tests.models import (
    DEFAULT_IMPRESSION_BUDGET,
    DEFAULT_SLOT_MINUTES,
    AbTest,
    AbTestStatus,
    TriggerMode,
)
from src.modules.ab_tests.repos import (
    AbTestRepository,
    CampaignRepository,
    ExposureRepository,
    SnapshotRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.schemas import (
    AbTestCreate,
    AbTestDetail,
    AbTestRead,
    AbTestSettingsUpdate,
)
from src.modules.ab_tests.services.detail import assemble_detail
from src.modules.ab_tests.services.finish import rotation_stopped_at
from src.modules.ab_tests.services.launch import Launcher
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.storage import MediaStore
from src.modules.ab_tests.services.triggers import TriggerSettings
from src.modules.ab_tests.services.triggers import resolve as resolve_trigger
from src.modules.monitoring.contract import WorkspaceCard

#: Route template the result rows point at for the picture itself.
IMAGE_URL_TEMPLATE = "/api/ab-tests/{test_id}/variants/{variant_id}/image"

#: Statuses a user may set by hand. ``completed`` is the rotation's to give.
_USER_SETTABLE = {AbTestStatus.RUNNING, AbTestStatus.PAUSED, AbTestStatus.CANCELLED}

#: Where a pause or a cancel may come from, with what a refusal says. A start
#: keeps its own guard in :class:`.launch.Launcher`. Pausing a finished test
#: used to succeed, and a start from that pause then passed the launcher — a
#: cancelled test came back and began rewriting the live card again. A draft is
#: not cancellable either: it has nothing to finish, and it can be deleted.
_STOP_SOURCES: dict[AbTestStatus, frozenset[str]] = {
    AbTestStatus.PAUSED: frozenset({AbTestStatus.RUNNING.value}),
    AbTestStatus.CANCELLED: frozenset({AbTestStatus.RUNNING.value, AbTestStatus.PAUSED.value}),
}


class AbTestCatalogService:
    """Create, edit and read A/B tests for one workspace."""

    def __init__(
        self,
        *,
        tests: AbTestRepository,
        variants: VariantRepository,
        exposures: ExposureRepository,
        stats: WindowRepository,
        snapshots: SnapshotRepository,
        campaigns: CampaignRepository,
        media_store: MediaStore,
    ) -> None:
        """Wire the service to its repositories and the WB installer.

        Args:
            tests: Test repository.
            variants: Variant repository.
            exposures: Exposure repository.
            stats: Per-interval traffic repository.
            snapshots: The poller's counter baseline, dropped on a pause so
                the paused stretch is not credited to anyone.
            campaigns: The register naming the advertising campaigns a test's
                traffic came from.
            media_store: Where variant originals are written and read.
        """
        self._tests = tests
        self._variants = variants
        self._exposures = exposures
        self._stats = stats
        self._snapshots = snapshots
        self._campaigns = campaigns
        self._media = media_store
        self._launcher = Launcher(tests=tests, exposures=exposures)

    # ----------------------------------------------------------------- reads

    async def list_tests(self, *, workspace_id: uuid.UUID, query: str | None) -> list[AbTestRead]:
        """Return the workspace's tests, newest first.

        Args:
            workspace_id: Owning workspace.
            query: Free-text needle matched against name, both articles and
                status; blank returns everything.

        Returns:
            List rows for the table.
        """
        tests = await self._tests.search(workspace_id=workspace_id, query=query)
        return [self._as_row(test) for test in tests]

    async def get_detail(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTestDetail:
        """Return one test with its per-photo result table.

        Args:
            workspace_id: Tenancy guard.
            test_id: Test identifier.

        Returns:
            The detail payload.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        windows = await self._stats.windows_for_test(test_id=test.id)
        # The open exposure's activation, not ``started_at``: the slot is
        # measured from when THIS photo went up, which is also exactly what the
        # time trigger compares against. Anything the UI derives from a
        # different clock would count down to a swap that happens elsewhere.
        active_since = await self._exposures.active_since(test_id=test.id)
        exposures = await self._exposures.history(test_id=test.id)
        campaigns = await self._campaigns.for_test(test_id=test.id)
        return assemble_detail(
            test=test,
            windows=windows,
            exposures=exposures,
            campaigns=campaigns,
            active_since=active_since,
            image_url=IMAGE_URL_TEMPLATE,
        )

    # ---------------------------------------------------------------- writes

    async def create_test(
        self,
        *,
        workspace_id: uuid.UUID,
        payload: AbTestCreate,
        card: WorkspaceCard | None,
    ) -> AbTestRead:
        """Create an empty draft test.

        It used to arrive carrying the card's live main photo, downloaded from
        WB's CDN as the baseline the uploads are read against. That is gone: WB
        serves **renditions**, not the seller's own file, so the baseline was a
        re-transcoded copy — and re-installing it put that loss back on the live
        card. The seller now uploads the baseline themselves and marks it
        «Главное»; see :meth:`.variants.VariantCatalogService.add_variant`.

        Args:
            workspace_id: Owning workspace.
            payload: Validated request body.
            card: The catalogue card ``payload.nm_id`` resolved to, or ``None``
                when the workspace owns no such article. Resolved by the router,
                which is where this repository's cross-module loaders are called
                from, so the service keeps no session of its own.

        Returns:
            The created test as a list row, with no photos in it yet.

        Raises:
            ValidationError: If the article is not in the workspace's catalogue,
                or if the workspace is at its test bound.
                Finished tests count — they keep their rows,
                their variants and their uploaded images.
        """
        # An article the workspace does not own cannot be rotated: it would send
        # a media upload at somebody else's card, or at nothing. The body was
        # trusted until 2026-09-05, when a test was created against article `1`.
        if card is None:
            raise ValidationError(f"Артикул {payload.nm_id} не найден в каталоге кабинета.")

        cap = settings.max_ab_tests_per_workspace
        if await self._tests.count_for_workspace(workspace_id) >= cap:
            raise ValidationError(
                f"Достигнут лимит А/Б-тестов ({cap} на кабинет). "
                "Удалите завершённые тесты, чтобы создать новый."
            )
        test = await self._tests.create(
            workspace_id=workspace_id,
            nm_id=payload.nm_id,
            vendor_code=card.vendor_code,
            name=payload.name,
            trigger_mode=payload.trigger_mode.value,
            # The create schema's validator has already resolved both numbers,
            # so neither is None by the time it reaches here.
            impression_budget=payload.impression_budget or DEFAULT_IMPRESSION_BUDGET,
            slot_minutes=payload.slot_minutes or DEFAULT_SLOT_MINUTES,
        )
        return self._as_row(test)

    async def update_settings(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, payload: AbTestSettingsUpdate
    ) -> AbTestRead:
        """Change a test's name or its rotation trigger, including mid-flight.

        Editing a RUNNING test is allowed on purpose — the point of being able
        to change the budget is to change it once you have seen how fast the
        card is actually gathering impressions. Two consequences the caller
        should know rather than discover:

        * Impressions already credited to the live photo are kept. Lowering the
          budget below what it has gathered therefore rotates on the very next
          poll, which is what "make it move faster, now" should do.
        * Switching to time mode measures the slot from when the photo was
          INSTALLED, not from when the mode changed, so a photo that has been up
          longer than the new slot also rotates on the next poll.

        A finished test is refused: its settings are the record of how its
        results were produced, and rewriting them would silently restate what
        the numbers on the page mean.

        Args:
            workspace_id: Tenancy guard.
            test_id: Test identifier.
            payload: The fields to change; every one is optional.

        Returns:
            The updated test.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
            ConflictError: If the test has already finished.
            ValidationError: If the change carries the setting belonging to the
                mode that will not be in force.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)

        if test.status in {AbTestStatus.COMPLETED.value, AbTestStatus.CANCELLED.value}:
            raise ConflictError("Настройки завершённого теста менять нельзя.")

        resolved = resolve_trigger(
            mode=payload.trigger_mode,
            impression_budget=payload.impression_budget,
            slot_minutes=payload.slot_minutes,
            current=TriggerSettings(
                mode=TriggerMode(test.trigger_mode),
                impression_budget=test.impression_budget,
                slot_minutes=test.slot_minutes,
            ),
        )

        await self._tests.update_settings(
            test=test,
            name=payload.name.strip() if payload.name else None,
            trigger_mode=resolved.mode.value,
            impression_budget=resolved.impression_budget,
            slot_minutes=resolved.slot_minutes,
        )
        return self._as_row(test)

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        status: str,
        installer: VariantInstaller,
    ) -> AbTestRead:
        """Start, pause or cancel a test.

        Starting installs whichever variant leads the rotation before the test
        is marked running — so a WB failure leaves the test exactly as it was.

        Stopping stamps ``stopped_at``, for a pause as much as for a cancel: the
        page has to say since when a test has been standing still, and only a
        cancelled one could answer that from ``finished_at``.

        Args:
            workspace_id: Tenancy guard.
            test_id: Test identifier.
            status: One of ``running``, ``paused``, ``cancelled``.
            installer: Puts the first photo on the card. Passed in per call
                rather than held on the service because building it needs the
                workspace's WB token, and reading a test must not require one —
                a workspace with no token can still look at its results.

        Returns:
            The updated test.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
            ValidationError: If the status is not one a user may set.
            ConflictError: If the test cannot make that transition — a pause
                of anything but a running test, a cancel of a draft or of a
                finished test, a start of a running or finished one.
            IntegrationError: If WB refuses the first photo.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        try:
            target = AbTestStatus(status)
        except ValueError as exc:
            raise ValidationError(f"Неизвестный статус: {status}.") from exc

        if target not in _USER_SETTABLE:
            raise ValidationError(f"Статус {status} выставляется автоматически.")

        _refuse_impossible_stop(current=test.status, target=target)

        now = datetime.now(UTC)
        if target is AbTestStatus.RUNNING:
            await self._launcher.launch(test=test, installer=installer, now=now)
        elif target is AbTestStatus.CANCELLED:
            # A paused test stopped at its pause, not now — see rotation_stopped_at.
            stopped = rotation_stopped_at(test, now=now)
            await self._exposures.close_open(test_id=test.id, deactivated_at=stopped)
            await self._tests.set_status(
                test=test, status=target, finished_at=now, stopped_at=stopped
            )
        else:
            # Dropping the counter baseline is what makes a pause a pause. WB's
            # counters are cumulative since midnight, so a baseline left behind
            # over a three-hour pause makes the first window after it three
            # hours wide and credits the lot to whichever photo is up — the
            # paused stretch would be paid for by the photo that did not serve
            # it. With no snapshot the next pass seeds and credits nothing.
            await self._snapshots.clear(test_id=test.id)
            await self._tests.set_status(test=test, status=target, stopped_at=now)

        return self._as_row(test)

    async def delete_test(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> None:
        """Delete a test and its variants.

        Args:
            workspace_id: Tenancy guard.
            test_id: Test identifier.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
        """
        if not await self._tests.delete(workspace_id=workspace_id, test_id=test_id):
            raise NotFoundError("Тест не найден.")

    # --------------------------------------------------------------- private

    def _as_row(self, test: AbTest) -> AbTestRead:
        """Project a test onto the list row the SPA renders.

        One builder rather than one per caller: every field added to the row
        since — the trigger mode, the slot length — would otherwise have to be
        remembered in four places.

        Args:
            test: A loaded test with its variants.

        Returns:
            The list row.
        """
        return AbTestRead(
            id=test.id,
            nm_id=test.nm_id,
            vendor_code=test.vendor_code,
            name=test.name,
            status=test.status,
            trigger_mode=test.trigger_mode,
            impression_budget=test.impression_budget,
            slot_minutes=test.slot_minutes,
            active_variant_id=test.active_variant_id,
            variant_count=len(test.variants),
            started_at=test.started_at,
            finished_at=test.finished_at,
            stopped_at=test.stopped_at,
            photo_conflict_at=test.photo_conflict_at,
            paused_by_ads=bool(test.paused_by_ads),
            created_at=test.created_at,
        )

    async def _require(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest:
        """Load a test or raise the 404 the router turns into a response."""
        test = await self._tests.get(workspace_id=workspace_id, test_id=test_id)
        if test is None:
            raise NotFoundError("Тест не найден.")
        return test


def _refuse_impossible_stop(*, current: str, target: AbTestStatus) -> None:
    """Raise the 409 for a pause or cancel the test's status does not allow.

    Args:
        current: The test's status as stored.
        target: The status the user asked for.

    Raises:
        ConflictError: If ``target`` is a pause or cancel not reachable from
            ``current``.
    """
    allowed = _STOP_SOURCES.get(target)
    if allowed is None or current in allowed:
        return
    if current in {AbTestStatus.COMPLETED.value, AbTestStatus.CANCELLED.value}:
        raise ConflictError("Тест уже завершён.")
    if target is AbTestStatus.PAUSED:
        raise ConflictError("Приостановить можно только запущенный тест.")
    raise ConflictError("Тест ещё не запущен — черновик можно удалить.")
