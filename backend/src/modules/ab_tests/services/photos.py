"""Validating an uploaded photo and putting one on the card.

Where the bytes are kept is :mod:`.storage`; this is what may be stored and what
happens when one goes up.

Installing writes **slot 1**, the main photo, through
``POST /content/v3/media/file``. The alternative (``media/save``) replaces the
entire gallery from a list of URLs, which would mean re-sending every other
image on the card and losing any this module does not know about.
"""

from __future__ import annotations

from typing import Protocol

from src.core.exceptions import ValidationError
from src.modules.ab_tests.models import AbTestVariant

#: WB's own ceiling for one media file.
MAX_IMAGE_BYTES: int = 32 * 1024 * 1024

#: The image formats WB documents for the media endpoints. Anything else is
#: refused locally so a doomed upload never reaches the seller's card — and
#: never spends a token from WB's media rate bucket.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}
)

#: WB numbers gallery slots from 1, and slot 1 is the main photo.
MAIN_PHOTO_NUMBER: int = 1


def validate_image(*, content: bytes, content_type: str) -> None:
    """Reject an upload WB would refuse anyway.

    Args:
        content: Raw bytes of the uploaded file.
        content_type: MIME type declared by the browser.

    Raises:
        ValidationError: If the file is empty, too large, or not an image
            format WB accepts.
    """
    if not content:
        raise ValidationError("Файл пустой.")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Формат {content_type} не поддерживается. Допустимы: JPG, PNG, WebP, BMP, GIF."
        )
    if len(content) > MAX_IMAGE_BYTES:
        raise ValidationError("Изображение больше 32 МБ — WB такой файл не примет.")


class _MediaReader(Protocol):
    """The part of the media store the installer needs."""

    async def read(self, relative_path: str) -> bytes: ...


class _MediaUploader(Protocol):
    """The part of ``WBContentClient`` the installer needs."""

    async def upload_media_file(
        self,
        *,
        nm_id: int,
        photo_number: int,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> None: ...


class VariantInstaller:
    """Puts one variant's image into the card's main photo slot."""

    def __init__(self, *, content_client: _MediaUploader, media_store: _MediaReader) -> None:
        """Wire the installer to WB and to the image store.

        Args:
            content_client: WB Content client used for the media upload.
            media_store: Where the variant originals are read from.
        """
        self._client = content_client
        self._store = media_store

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None:
        """Send the variant's image to WB as the card's main photo.

        The bytes are replayed exactly as stored: the variant's digest is what
        ties a picture to the metrics it earned, so any re-encoding on the way
        out would break that link.

        Args:
            nm_id: The card being rotated.
            variant: The variant whose image goes up.

        Raises:
            IntegrationError: If WB rejects the upload — deliberately not caught,
                because a caller that recorded an exposure anyway would attribute
                the next days to a photo that never went live.
        """
        content = await self._store.read(variant.image_path)
        await self._client.upload_media_file(
            nm_id=nm_id,
            photo_number=MAIN_PHOTO_NUMBER,
            content=content,
            filename=variant.original_filename or f"{variant.id}.jpg",
            content_type=variant.content_type,
        )
