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
from src.core.logging import get_logger
from src.modules.ab_tests.models import MAX_VARIANTS_PER_TEST, AbTest, AbTestVariant
from src.modules.ab_tests.repos import AbTestRepository, VariantRepository, WindowRepository
from src.modules.ab_tests.services.photos import validate_image
from src.modules.ab_tests.services.storage import MediaStore
from src.modules.ab_tests.services.thumbnails import (
    THUMBNAIL_CONTENT_TYPE,
    derive,
    thumbnail_key,
)

logger = get_logger(__name__)


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
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        thumbnail: bool = False,
    ) -> tuple[bytes, str]:
        """Return one variant's stored image and its MIME type.

        ``thumbnail`` serves a small JPEG copy instead — see
        :mod:`.thumbnails` for why every screen wants one. It is derived on the
        first request and kept, so the cost is paid once per image rather than
        once per page.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            variant_id: Variant identifier.
            thumbnail: Serve the small copy rather than the original.

        Returns:
            ``(bytes, content_type)``.

        Raises:
            NotFoundError: If the test, the variant, or the file is missing.
        """
        # One query, not three: this is the only route called once per PHOTO,
        # and resolving the test separately made a nine-photo page spend
        # twenty-seven round trips on a guard that one join expresses.
        variant = await self._variants.get_scoped(
            workspace_id=workspace_id, test_id=test_id, variant_id=variant_id
        )
        if variant is None:
            raise NotFoundError("Вариант не найден.")
        try:
            if thumbnail:
                return await self._thumbnail(variant.image_path), THUMBNAIL_CONTENT_TYPE
            return await self._media.read(variant.image_path), variant.content_type
        except FileNotFoundError as exc:  # pragma: no cover - disk-level failure
            raise NotFoundError("Файл изображения отсутствует в хранилище.") from exc

    async def _warm_thumbnail(self, image_path: str, content: bytes) -> None:
        """Derive and cache the small copy of an image just uploaded.

        Never raises: a thumbnail that could not be made is a slower page, and
        failing the upload over it would lose the photo instead.

        Args:
            image_path: Where the original was just stored.
            content: The bytes that were stored, already in hand.
        """
        try:
            small = await derive(content)
            await self._media.put(
                relative_path=thumbnail_key(image_path),
                content=small,
                content_type=THUMBNAIL_CONTENT_TYPE,
            )
        except Exception as exc:
            logger.warning("ab_tests: could not pre-size %s: %s", image_path, exc)

    async def _thumbnail(self, image_path: str) -> bytes:
        """Return the small copy of one original, making it if it is not there.

        A failure to derive or to cache is not a failure to answer: the caller
        gets the original, which is the slow answer rather than no answer. What
        must not happen is a photo missing from the page because a re-encode
        went wrong — the picture is the row.

        Args:
            image_path: The original's path, as stored on the variant row.

        Returns:
            JPEG bytes of the derivative, or the original's bytes on failure.
        """
        key = thumbnail_key(image_path)
        try:
            return await self._media.read(key)
        except FileNotFoundError:
            # The usual path the first time an image is asked for.
            pass
        except Exception as exc:
            # An unreachable bucket fails the read below too, and that one is
            # allowed to propagate — this branch only reports what it saw.
            logger.info("ab_tests: thumbnail read failed for %s: %s", key, exc)

        original = await self._media.read(image_path)
        try:
            small = await derive(original)
        except Exception as exc:
            logger.warning("ab_tests: could not resize %s, serving it whole: %s", image_path, exc)
            return original

        try:
            await self._media.put(
                relative_path=key, content=small, content_type=THUMBNAIL_CONTENT_TYPE
            )
        except Exception as exc:
            # Serving it uncached is slow, not wrong; the next request retries.
            logger.warning("ab_tests: could not cache the thumbnail of %s: %s", image_path, exc)
        return small

    async def add_variant(
        self,
        *,
        workspace_id: uuid.UUID,
        test_id: uuid.UUID,
        content: bytes,
        content_type: str,
        filename: str,
        as_main: bool = False,
    ) -> AbTestVariant:
        """Store an uploaded photo and put it in the rotation.

        ``as_main`` files it as «Главное» — position 0, first out of the gate,
        the row every other photo is read against. It is an upload like any
        other, and that is the change: the baseline used to be pulled off WB's
        CDN, which meant comparing against a rendition of the seller's file
        rather than against the file, and pushing that transcoding loss back
        onto the live card every time it came round again.

        Args:
            workspace_id: Tenancy guard.
            test_id: Owning test.
            content: Raw image bytes.
            content_type: MIME type declared by the browser.
            filename: The user's own file name.
            as_main: File it as the test's «Главное» photo.

        Returns:
            The new variant.

        Raises:
            NotFoundError: If the test does not exist in this workspace.
            ValidationError: If the file is not an image WB would accept.
            ConflictError: If the test already carries the maximum photos, or
                already has a «Главное» one.
        """
        test = await self._require(workspace_id=workspace_id, test_id=test_id)
        validate_image(content=content, content_type=content_type)

        if await self._variants.count_for_test(test_id=test.id) >= MAX_VARIANTS_PER_TEST:
            raise ConflictError(f"В тесте не может быть больше {MAX_VARIANTS_PER_TEST} фото.")

        if as_main and any(variant.is_original for variant in test.variants):
            raise ConflictError("Главное фото уже загружено. Удалите его, чтобы загрузить другое.")

        stored = await self._media.save(content=content, content_type=content_type, test_id=test.id)
        # Derive the small copy NOW, while the seller is already waiting on an
        # upload, rather than on whoever opens the page first. Deriving costs
        # about as long as the upload itself, and a page that pays it for ten
        # photos at once is the slow first load this whole thing exists to
        # remove. Best-effort: the read path makes one if this did not.
        await self._warm_thumbnail(stored.relative_path, content)

        add = self._variants.add_original if as_main else self._variants.add
        return await add(
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

        «Главное» may be deleted like any other photo — it is an upload, and
        deleting it is how it is replaced. It was refused while it was captured
        from WB, when deleting it meant losing a baseline the seller could not
        put back.

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
