"""Request-scoped operations on tests and their photos.

Everything a user does from the SPA: create a test, upload and remove photos,
start / pause / cancel it, and read the result table. The rotation itself runs
without a request (see :mod:`.runner`), and the two meet at
:class:`~src.modules.ab_tests.services.photos.VariantInstaller`.

Starting a test installs its first photo **synchronously**. It is one WB call,
and doing it in the background would leave the user looking at a «Запущен» test
whose card still shows the old image, with the failure buried in a worker log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.config import settings
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.modules.ab_tests.models import (
    MAX_VARIANTS_PER_TEST,
    AbTest,
    AbTestStatus,
    AbTestVariant,
)
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    VariantRepository,
    VariantStatRepository,
)
from src.modules.ab_tests.schemas import AbTestCreate, AbTestDetail, AbTestRead
from src.modules.ab_tests.services.photos import MediaStore, VariantInstaller, validate_image
from src.modules.ab_tests.services.results import build_rows, leader_of

#: Route template the result rows point at for the picture itself.
IMAGE_URL_TEMPLATE = "/api/ab-tests/{test_id}/variants/{variant_id}/image"

#: Statuses a user may set by hand. ``completed`` is the rotation's to give.
_USER_SETTABLE = {AbTestStatus.RUNNING, AbTestStatus.PAUSED, AbTestStatus.CANCELLED}


class AbTestCatalogService:
    """Create, edit and read A/B tests for one workspace."""

    def __init__(
        self,
        *,
        tests: AbTestRepository,
        variants: VariantRepository,
        exposures: ExposureRepository,
        stats: VariantStatRepository,
        media_store: MediaStore,
    ) -> None:
        """Wire the service to its repositories and the WB installer.

        Args:
            tests: Test repository.
            variants: Variant repository.
            exposures: Exposure repository.
            stats: Attributed-day repository.
            media_store: Where variant originals are written and read.
        """
        self._tests = tests
        self._variants = variants
        self._exposures = exposures
        self._stats = stats
        self._media = media_store

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
        return [
            AbTestRead(
                id=test.id,
                nm_id=test.nm_id,
                vendor_code=test.vendor_code,
                name=test.name,
                status=test.status,
                impression_budget=test.impression_budget,
                active_variant_id=test.active_variant_id,
                variant_count=len(test.variants),
                started_at=test.started_at,
                finished_at=test.finished_at,
                created_at=test.created_at,
            )
            for test in tests
        ]

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
        days = await self._stats.days_for_test(test_id=test.id)
        rows = build_rows(
            test=test, variants=test.variants, days=days, image_url=IMAGE_URL_TEMPLATE
        )
        return AbTestDetail(
            id=test.id,
            nm_id=test.nm_id,
            vendor_code=test.vendor_code,
            name=test.name,
            status=test.status,
            impression_budget=test.impression_budget,
            active_variant_id=test.active_variant_id,
            variant_count=len(test.variants),
            started_at=test.started_at,
            finished_at=test.finished_at,
            created_at=test.created_at,
            leader_variant_id=leader_of(rows),
            variants=rows,
        )

    async def read_variant_image(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, variant_id: uuid.UUID
    ) -> tuple[bytes, str]:
        """Return one variant's stored image and its MIME type.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            variant_id: Variant identifier.

        Returns:
            ``(bytes, content_type)``.

        Raises:
            NotFoundError: If the test, the variant, or the file is missing.
        """
        await self._require(workspace_id=workspace_id, test_id=test_id)
        variant = await self._variants.get(test_id=test_id, variant_id=variant_id)
        if variant is None:
            raise NotFoundError("Вариант не найден.")
        try:
            return self._media.read(variant.image_path), variant.content_type
        except FileNotFoundError as exc:  # pragma: no cover - disk-level failure
            raise NotFoundError("Файл изображения отсутствует в хранилище.") from exc

    # ---------------------------------------------------------------- writes

    async def create_test(self, *, workspace_id: uuid.UUID, payload: AbTestCreate) -> AbTestRead:
        """Create a draft test.

        Args:
            workspace_id: Owning workspace.
            payload: Validated request body.

        Returns:
            The created test as a list row.

        Raises:
            ValidationError: If the workspace is at its test bound
                (register P1.13). Finished tests count — they keep their rows,
                their variants and their uploaded images.
        """
        cap = settings.max_ab_tests_per_workspace
        if await self._tests.count_for_workspace(workspace_id) >= cap:
            raise ValidationError(
                f"Достигнут лимит А/Б-тестов ({cap} на воркспейс). "
                "Удалите завершённые тесты, чтобы создать новый."
            )
        test = await self._tests.create(
            workspace_id=workspace_id,
            nm_id=payload.nm_id,
            vendor_code=payload.vendor_code,
            name=payload.name,
            impression_budget=payload.impression_budget,
        )
        return AbTestRead(
            id=test.id,
            nm_id=test.nm_id,
            vendor_code=test.vendor_code,
            name=test.name,
            status=test.status,
            impression_budget=test.impression_budget,
            active_variant_id=None,
            variant_count=0,
            started_at=None,
            finished_at=None,
            created_at=test.created_at,
        )

    async def add_variant(
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        content: bytes,
        content_type: str,
        filename: str,
    ) -> AbTestVariant:
        """Store an uploaded photo and append it to the rotation.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            content: Raw image bytes.
            content_type: MIME type declared by the browser.
            filename: The user's own file name.

        Returns:
            The new variant.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
            ValidationError: If the file is not an image WB would accept.
            ConflictError: If the test already carries the maximum photos.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        validate_image(content=content, content_type=content_type)

        if await self._variants.count_for_test(test_id=test.id) >= MAX_VARIANTS_PER_TEST:
            raise ConflictError(f"В тесте не может быть больше {MAX_VARIANTS_PER_TEST} фото.")

        stored = self._media.save(content=content, content_type=content_type, test_id=test.id)
        return await self._variants.add(
            test_id=test.id,
            image_path=stored.relative_path,
            image_sha256=stored.sha256,
            content_type=content_type,
            original_filename=filename,
        )

    async def delete_variant(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, variant_id: uuid.UUID
    ) -> None:
        """Remove a photo from a test.

        The stored file stays on disk when the variant was ever live: its bytes
        are the evidence behind the metrics already attributed to it.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            variant_id: Variant identifier.

        Raises:
            NotFoundError: If the test or the variant does not exist.
            ConflictError: If the variant is the one currently on the card.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        if test.active_variant_id == variant_id:
            raise ConflictError("Нельзя удалить фото, которое сейчас стоит на карточке.")

        variant = await self._variants.get(test_id=test_id, variant_id=variant_id)
        if variant is None:
            raise NotFoundError("Вариант не найден.")

        never_measured = await self._stats.impressions_for_variant(variant_id=variant_id) == 0
        path = variant.image_path

        await self._variants.delete(test_id=test_id, variant_id=variant_id)
        if never_measured:
            self._media.delete(path)

    async def set_status(
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        status: str,
        installer: VariantInstaller,
    ) -> AbTestRead:
        """Start, pause or cancel a test.

        Starting installs the first photo on the card before the test is marked
        running, so a WB failure leaves the test exactly as it was.

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
            ConflictError: If the test cannot make that transition.
            IntegrationError: If WB refuses the first photo.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        try:
            target = AbTestStatus(status)
        except ValueError as exc:
            raise ValidationError(f"Неизвестный статус: {status}.") from exc

        if target not in _USER_SETTABLE:
            raise ValidationError(f"Статус {status} выставляется автоматически.")

        if target is AbTestStatus.RUNNING:
            await self._start(test, installer)
        elif target is AbTestStatus.CANCELLED:
            await self._exposures.close_open(test_id=test.id, deactivated_at=datetime.now(UTC))
            await self._tests.set_status(test=test, status=target, finished_at=datetime.now(UTC))
        else:
            await self._tests.set_status(test=test, status=target)

        return AbTestRead(
            id=test.id,
            nm_id=test.nm_id,
            vendor_code=test.vendor_code,
            name=test.name,
            status=test.status,
            impression_budget=test.impression_budget,
            active_variant_id=test.active_variant_id,
            variant_count=len(test.variants),
            started_at=test.started_at,
            finished_at=test.finished_at,
            created_at=test.created_at,
        )

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

    async def _start(self, test: AbTest, installer: VariantInstaller) -> None:
        """Put the first photo up and mark the test running.

        A paused test resumes on whatever photo is already installed rather
        than restarting the rotation.
        """
        if test.status == AbTestStatus.RUNNING.value:
            raise ConflictError("Тест уже запущен.")
        if test.status in {AbTestStatus.COMPLETED.value, AbTestStatus.CANCELLED.value}:
            raise ConflictError("Завершённый тест нельзя запустить повторно.")
        if not test.variants:
            raise ConflictError("Загрузите хотя бы одно фото, прежде чем запускать тест.")

        now = datetime.now(UTC)
        if test.active_variant_id is None:
            first = test.variants[0]
            await installer.install(nm_id=test.nm_id, variant=first)
            await self._exposures.open(test_id=test.id, variant_id=first.id, activated_at=now)
            await self._tests.set_active_variant(test=test, variant_id=first.id)

        await self._tests.set_status(
            test=test,
            status=AbTestStatus.RUNNING,
            started_at=test.started_at or now,
        )

    async def _require(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest:
        """Load a test or raise the 404 the router turns into a response."""
        test = await self._tests.get(workspace_id=workspace_id, test_id=test_id)
        if test is None:
            raise NotFoundError("Тест не найден.")
        return test
