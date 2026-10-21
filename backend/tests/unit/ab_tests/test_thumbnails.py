"""Unit tests for the derived thumbnails (services/thumbnails.py).

The reason this exists is a measurement rather than a preference — fourteen
full-size variant images came to 78.8 MB, drawn at up to 88 CSS pixels — so what is
worth pinning is that the derivative is actually small, and that the formats a
seller really uploads survive the trip. A phone photo is as likely to be a PNG
with an alpha channel or a portrait JPEG carrying its rotation in EXIF as it is
to be a plain RGB one, and each of those has its own way of coming out wrong:
an exception, a black background, a picture on its side.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.core.exceptions import ValidationError
from src.modules.ab_tests.services.thumbnails import (
    THUMBNAIL_MAX_EDGE,
    derive,
    thumbnail_key,
)


def _image(size: tuple[int, int], mode: str = "RGB", fmt: str = "PNG") -> bytes:
    """Encode a plain test image."""
    buffer = io.BytesIO()
    Image.new(mode, size, (200, 30, 40) if mode == "RGB" else None).save(buffer, format=fmt)
    return buffer.getvalue()


async def test_a_large_photo_comes_back_within_the_edge_bound() -> None:
    """The point of the whole module: a big picture becomes a small one."""
    original = _image((4032, 3024))

    small = await derive(original)

    with Image.open(io.BytesIO(small)) as result:
        assert max(result.size) == THUMBNAIL_MAX_EDGE
        assert result.format == "JPEG"
    assert len(small) < len(original) / 10


async def test_a_small_photo_is_not_blown_up() -> None:
    """`Image.thumbnail` only ever shrinks, and that is the behaviour wanted."""
    small = await derive(_image((120, 90)))

    with Image.open(io.BytesIO(small)) as result:
        assert result.size == (120, 90)


async def test_a_transparent_png_is_flattened_rather_than_refused() -> None:
    """JPEG has no alpha, and a seller's cut-out photo is a PNG with one.

    Saving an RGBA image as JPEG raises. Left unhandled, the whole derivation
    would fail and the page would serve the multi-megabyte original instead —
    the slow path, for the images most likely to be large.
    """
    transparent = _image((900, 900), mode="RGBA")

    small = await derive(transparent)

    with Image.open(io.BytesIO(small)) as result:
        assert result.mode == "RGB"


async def test_a_portrait_photo_keeps_its_orientation() -> None:
    """EXIF rotation is in the metadata, not in the pixels.

    A phone photo taken upright is stored landscape with an orientation tag.
    Dropping the tag on re-encode — which JPEG output does — leaves the
    thumbnail on its side next to an original WB shows the right way up.
    """
    upright = Image.new("RGB", (600, 400), (10, 10, 10))
    exif = upright.getexif()
    exif[274] = 6  # Rotate 90° CW on display.
    buffer = io.BytesIO()
    upright.save(buffer, format="JPEG", exif=exif)

    small = await derive(buffer.getvalue())

    with Image.open(io.BytesIO(small)) as result:
        # The tag said "this is portrait"; the pixels now say so too.
        assert result.height > result.width


async def test_something_that_is_not_an_image_is_refused() -> None:
    """The caller falls back to the original, so this must raise rather than
    return the bytes it was given."""
    with pytest.raises(ValidationError):
        await derive(b"not an image at all")


def test_the_key_hangs_off_the_originals_own_key() -> None:
    """The original's key carries its content digest, so the derivative's does
    too — a derivative can never be served for a different image."""
    assert thumbnail_key("test-id/abc123.png").startswith("test-id/abc123.png")
