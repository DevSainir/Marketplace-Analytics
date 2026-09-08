"""The photos of a test: uploading them, taking them out, serving them back.

Split from :mod:`.catalog`, which is about the test — creating it, starting it,
changing its trigger. This is about the pictures in it, and the two grew apart
the moment a photo could be excluded as well as added and removed.

Every method here is scoped by the test, and the test by the workspace, so a
photo of somebody else's test reads as absent rather than forbidden — the same
rule the rest of the module follows.
"""

# ruff: noqa: RUF001 — user-facing error messages are written in
# Russian, and the confusable-character check fires on ordinary Cyrillic.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.ab_tests.models import MAX_VARIANTS_PER_TEST, AbTest, AbTestVariant
from src.modules.ab_tests.repos import AbTestRepository, VariantRepository, WindowRepository
from src.modules.ab_tests.services.photos import validate_image
from src.modules.ab_tests.services.storage import MediaStore


class VariantCatalogService:
    """Create, remove, exclude and read the photos of one workspace's tests."""

    def __init__(
        self,
        *,
        tests: AbTestRepository,
        variants: VariantRepository,
        stats: WindowRepository,
        media_store: MediaStore,
    ) -> None:
        """Wire the service to its repositories and the image store.

        Args:
            tests: Test repository, used only to resolve the owning test.
            variants: Variant repository.
            stats: Per-interval traffic, consulted before deleting an image.
            media_store: Where variant originals are written and read.
        """
        self._tests = tests
        self._variants = variants
        self._stats = stats
        self._media = media_store

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
            return await self._media.read(variant.image_path), variant.content_type
        except FileNotFoundError as exc:  # pragma: no cover - disk-level failure
            raise NotFoundError("Файл изображения отсутствует в хранилище.") from exc

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

        stored = await self._media.save(content=content, content_type=content_type, test_id=test.id)
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
            ConflictError: If the variant is the one currently on the card, or
                is the card's own photo — that one is the baseline every other
                row is read against, and a table without it compares the
                candidates only to each other.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        if test.active_variant_id == variant_id:
            raise ConflictError("Нельзя удалить фото, которое сейчас стоит на карточке.")

        variant = await self._variants.get(test_id=test_id, variant_id=variant_id)
        if variant is None:
            raise NotFoundError("Вариант не найден.")
        if variant.is_original:
            raise ConflictError(
                "Текущее фото карточки убрать из ротации нельзя — с ним сравниваются остальные."
            )

        never_measured = await self._stats.impressions_for_variant(variant_id=variant_id) == 0
        path = variant.image_path

        await self._variants.delete(test_id=test_id, variant_id=variant_id)
        if never_measured:
            await self._media.delete(path)

    async def set_variant_excluded(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, variant_id: uuid.UUID, excluded: bool
    ) -> AbTestVariant:
        """Take a photo out of the rotation, or put it back.

        Allowed on a running test on purpose — that is the whole point. A seller
        watching a photo lose four laps in a row should be able to stop dealing
        it without cancelling the test and losing what the others have earned.

        Nothing is deleted: the row, the image and every window already credited
        to it stay, so the result table goes on showing what it did. Excluding
        the photo that is currently up takes it off the card on the next pass
        rather than at the end of its slot — «убрать» has to mean now.

        The last photo still in the rotation cannot be excluded: a rotation with
        nothing to deal would hold forever with whatever is on the card, which
        is a stuck test wearing the costume of a running one.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            variant_id: The photo to exclude or restore.
            excluded: ``True`` to take it out, ``False`` to bring it back.

        Returns:
            The updated variant.

        Raises:
            NotFoundError: If the test or the variant does not exist here.
            ConflictError: If this is the last photo left in the rotation.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        variant = await self._variants.get(test_id=test_id, variant_id=variant_id)
        if variant is None:
            raise NotFoundError("Вариант не найден.")

        remaining = [v for v in test.variants if not v.is_excluded and v.id != variant_id]
        if excluded and not remaining:
            raise ConflictError(
                "Это последнее фото в ротации — убрав его, тесту нечего будет показывать."
            )

        return await self._variants.set_excluded(
            variant=variant, excluded_at=datetime.now(UTC) if excluded else None
        )

    async def _require(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest:
        """Load a test or raise the 404 the router turns into a response."""
        test = await self._tests.get(workspace_id=workspace_id, test_id=test_id)
        if test is None:
            raise NotFoundError("Тест не найден.")
        return test


__all__ = ["VariantCatalogService"]
