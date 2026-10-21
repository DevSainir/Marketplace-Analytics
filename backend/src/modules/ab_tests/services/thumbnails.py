"""Small copies of the variant photos, for every screen that shows one.

Measured before this existed: fourteen variant images are
**78.8 MB**, mostly phone PNGs of eight or nine megabytes each. Every surface
that displays one draws it between 24 and 88 CSS pixels — the result table's
thumbnail, the timeline's markers, the log. The detail page was therefore
downloading tens of megabytes to paint pictures the size of a postage stamp,
which is the whole of "it takes 10-15 seconds to load".

The full image is still what goes to WB. Nothing here touches the original: the
rotation reads the stored bytes and uploads them, and a re-encode in that path
is exactly the quality loss the module stopped taking from WB's own CDN.

Derived **once and kept**. The key is the original's, plus a suffix naming the
size, so a derivative can never be served for the wrong image: the original's
key already contains its content digest.

Two bounds, because this decodes a file a user uploaded:

* **Pixels.** A 32 MB upload is within the module's limit and can still be a
  200-megapixel PNG that costs gigabytes to decode. Pillow's own bomb guard is
  raised as an error rather than a warning, and the ceiling is set where no
  photograph of a dress will reach it.
* **Concurrency.** Decoding is CPU and memory, and it runs in the api container
  next to every request that is not this one. Two at a time, in a worker thread
  so the event loop keeps answering.
"""

from __future__ import annotations

import asyncio
import io
import weakref

from PIL import Image, ImageOps
from PIL.Image import Resampling

from src.core.exceptions import ValidationError

#: Longest edge of a derived image, in pixels. The largest place any of these
#: are drawn is 88 CSS px, so this covers a 3x display with room to spare.
THUMBNAIL_MAX_EDGE: int = 512

#: JPEG quality. 82 is where the difference stops being visible at these sizes.
_QUALITY: int = 82

#: Suffix appended to the original's key. Part of the cache identity, so raising
#: THUMBNAIL_MAX_EDGE means changing this too — otherwise the old, smaller
#: derivative keeps being served under a name that now claims a bigger one.
THUMBNAIL_SUFFIX: str = f".t{THUMBNAIL_MAX_EDGE}.jpg"

#: What a derivative is always served as.
THUMBNAIL_CONTENT_TYPE: str = "image/jpeg"

#: Pixels one upload may decode to. Pillow warns past ~89 Mpx and errors at
#: twice that; this is well under both and well over any real photograph.
_MAX_PIXELS: int = 50_000_000

#: How many images may be decoded at once. The api container serves everything
#: else meanwhile, and one 9 MB PNG is ~50 MB of bitmap while it is open.
_LANE_WIDTH: int = 2

#: One lane per running event loop. A module-level ``asyncio.Semaphore`` binds to
#: the first loop that waits on it and raises in every other — each Celery task
#: runs its own loop (``tests/unit/core/test_no_loop_bound_state_outlives_a_task.py``).
_lanes: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


def _lane() -> asyncio.Semaphore:
    """The decode lane for the event loop that is running now."""
    loop = asyncio.get_running_loop()
    lane = _lanes.get(loop)
    if lane is None:
        lane = _lanes[loop] = asyncio.Semaphore(_LANE_WIDTH)
    return lane


def thumbnail_key(image_path: str) -> str:
    """Key the derivative of one original is stored under.

    Args:
        image_path: The original's path, as stored on the variant row.

    Returns:
        The derivative's path in the same store.
    """
    return f"{image_path}{THUMBNAIL_SUFFIX}"


def _shrink(content: bytes) -> bytes:
    """Decode, downscale and re-encode one image as JPEG.

    Synchronous on purpose — the caller runs it in a thread. Kept separate from
    :func:`derive` so the bounds and the threading are readable apart from the
    image handling.

    Args:
        content: Raw bytes of the original.

    Returns:
        JPEG bytes, no edge longer than :data:`THUMBNAIL_MAX_EDGE`.

    Raises:
        ValidationError: If the bytes are not a decodable image, or decode to
            more pixels than this is willing to spend memory on.
    """
    try:
        with Image.open(io.BytesIO(content)) as source:
            width, height = source.size
            if width * height > _MAX_PIXELS:
                raise ValidationError("Изображение слишком большое для обработки.")
            # Ask the JPEG decoder for a smaller picture in the first place.
            # libjpeg can scale by halves while decoding, so a 12-megapixel
            # photo is never fully expanded: measured 3.9 s -> 0.4 s on the
            # same file. A no-op for PNG, which has no such mode.
            source.draft("RGB", (THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
            # Phone photos carry their rotation in EXIF rather than in the
            # pixels; without this the thumbnail of a portrait shot is on its
            # side while the original WB receives is not.
            image = ImageOps.exif_transpose(source)
            # `reducing_gap` does the bulk of the shrinking with a cheap box
            # filter and leaves LANCZOS the last factor of two, where it is the
            # only part anyone can see.
            image.thumbnail(
                (THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Resampling.LANCZOS, reducing_gap=2.0
            )
            # JPEG has no alpha. A PNG with transparency would otherwise raise,
            # and the screens these appear on are white.
            if image.mode in {"RGBA", "LA", "P"}:
                flattened = Image.new("RGB", image.size, (255, 255, 255))
                converted = image.convert("RGBA")
                flattened.paste(converted, mask=converted.split()[-1])
                image = flattened
            elif image.mode != "RGB":
                image = image.convert("RGB")

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=_QUALITY, optimize=True)
            return buffer.getvalue()
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Не удалось обработать изображение.") from exc


async def derive(content: bytes) -> bytes:
    """Return a small JPEG copy of one image.

    Args:
        content: Raw bytes of the original.

    Returns:
        JPEG bytes, no edge longer than :data:`THUMBNAIL_MAX_EDGE`.

    Raises:
        ValidationError: If the image cannot be decoded or is too large.
    """
    async with _lane():
        return await asyncio.to_thread(_shrink, content)


__all__ = [
    "THUMBNAIL_CONTENT_TYPE",
    "THUMBNAIL_MAX_EDGE",
    "THUMBNAIL_SUFFIX",
    "derive",
    "thumbnail_key",
]
