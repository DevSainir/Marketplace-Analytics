"""Unit tests for uploading and installing a variant photo (services/photos.py).

Installing a variant is the only thing this module does that **changes the
seller's live storefront**, so the checks around it are worth more than the
rotation arithmetic: a bad upload is visible to buyers, and a silent no-op makes
every downstream metric a lie about an image that never actually went up.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from src.core.exceptions import IntegrationError, ValidationError
from src.modules.ab_tests.models import AbTestVariant
from src.modules.ab_tests.services.photos import (
    MAX_IMAGE_BYTES,
    VariantInstaller,
    validate_image,
)

# Sample vendor codes, so a reader can tell which card each case stands for.
VENDOR_FLOWER_DRESS = "ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК"
VENDOR_PLAIN_SUIT = "ДЕТ_КОСТЮМ_ДВОЙКА_ОДНОТОН"
VENDOR_DENIM_SUIT = "ДЖН_КОСТЮМ_ДЖИНСА"

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 2048


@dataclass
class _Upload:
    """One recorded call to WB's media endpoint."""

    nm_id: int
    photo_number: int
    content: bytes
    content_type: str


class _FakeContentClient:
    """Stand-in for ``WBContentClient`` that records what would be sent."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.uploads: list[_Upload] = []
        self._fail_with = fail_with

    async def upload_media_file(
        self,
        *,
        nm_id: int,
        photo_number: int,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.uploads.append(_Upload(nm_id, photo_number, content, content_type))


class _FakeMediaStore:
    """In-memory stand-in for the media store.

    ``read`` is async because the real one is: the originals live in object
    storage now, shared by the api that writes them and the worker that reads
    them back.
    """

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def read(self, relative_path: str) -> bytes:
        return self.files[relative_path]


def _variant(path: str = "a/b.jpg", content_type: str = "image/jpeg") -> AbTestVariant:
    """A persisted variant pointing at a stored image."""
    return AbTestVariant(
        id=uuid.uuid4(),
        test_id=uuid.uuid4(),
        position=1,
        image_path=path,
        image_sha256="0" * 64,
        content_type=content_type,
        original_filename="photo.jpg",
    )


# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #


def test_a_jpeg_within_limits_is_accepted() -> None:
    """The ordinary upload passes without raising."""
    validate_image(content=JPEG, content_type="image/jpeg")


@pytest.mark.parametrize("content_type", ["application/pdf", "text/html", "video/mp4"])
def test_a_non_image_is_refused(content_type: str) -> None:
    """WB accepts a fixed set of image formats; anything else fails here.

    Refusing locally keeps a doomed upload from reaching the seller's card and
    from burning a slot in WB's media rate bucket.
    """
    with pytest.raises(ValidationError):
        validate_image(content=JPEG, content_type=content_type)


def test_an_oversized_image_is_refused() -> None:
    """WB caps a media file at 32 MB; larger uploads are rejected up front."""
    with pytest.raises(ValidationError, match="32"):
        validate_image(content=b"0" * (MAX_IMAGE_BYTES + 1), content_type="image/jpeg")


def test_an_empty_upload_is_refused() -> None:
    """A zero-byte part is a broken form post, not a picture."""
    with pytest.raises(ValidationError):
        validate_image(content=b"", content_type="image/jpeg")


# --------------------------------------------------------------------------- #
# Installing a variant on the card
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("vendor_code", "nm_id"),
    [
        (VENDOR_FLOWER_DRESS, 995716075),
        (VENDOR_PLAIN_SUIT, 1948347102),
        (VENDOR_DENIM_SUIT, 953770957),
    ],
)
async def test_installing_a_variant_writes_the_main_photo_slot(
    vendor_code: str, nm_id: int
) -> None:
    """The stored image is sent to WB as photo number 1 of the right card.

    Slot 1 is the main photo — the only one the rotation is allowed to touch.
    Writing any other slot would leave the card's main image unchanged while the
    module went on attributing impressions to the "new" variant.
    """
    variant = _variant(path="tests/one.jpg")
    client = _FakeContentClient()
    installer = VariantInstaller(
        content_client=client, media_store=_FakeMediaStore({"tests/one.jpg": JPEG})
    )

    await installer.install(nm_id=nm_id, variant=variant)

    assert len(client.uploads) == 1
    upload = client.uploads[0]
    assert (upload.nm_id, upload.photo_number) == (nm_id, 1)
    assert upload.content == JPEG
    assert vendor_code  # the card these ids belong to, for the reader


async def test_the_bytes_sent_are_the_bytes_stored() -> None:
    """WB receives exactly what the user uploaded, not a re-encoding.

    The variant's digest is what proves which picture earned which metrics, so
    anything that rewrites the bytes on the way out breaks that link.
    """
    original = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8
    client = _FakeContentClient()
    installer = VariantInstaller(
        content_client=client, media_store=_FakeMediaStore({"v/1.jpg": original})
    )

    await installer.install(nm_id=995716075, variant=_variant(path="v/1.jpg"))

    assert client.uploads[0].content == original


async def test_a_wb_rejection_propagates_instead_of_being_swallowed() -> None:
    """A failed upload must not look like a successful rotation.

    If this returned quietly the caller would record an exposure for a photo
    that never went up, and every metric attributed to it afterwards would
    describe the previous image.
    """
    installer = VariantInstaller(
        content_client=_FakeContentClient(fail_with=IntegrationError("WB said no")),
        media_store=_FakeMediaStore({"v/1.jpg": JPEG}),
    )

    with pytest.raises(IntegrationError):
        await installer.install(nm_id=995716075, variant=_variant(path="v/1.jpg"))
