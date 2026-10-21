"""Serving a variant's picture: the thumbnail is derived once and kept.

The cost this is about is real and measured — full-size originals are eight and
nine megabytes each — but the cost of the FIX is real too: decoding a 9 MB
PNG is CPU and about fifty megabytes of bitmap. Doing it on every request would
trade a slow page for a slow server, so "derived once" is the property that makes
the whole thing worth having, and it is the one that silently stops holding if a
cache write is dropped or a key is computed two different ways.

The fallback matters as much. A picture is what the row IS on these screens, so a
re-encode that fails has to serve the original rather than nothing.
"""

from __future__ import annotations

import io
import uuid

import pytest
from PIL import Image

from src.core.exceptions import NotFoundError
from src.core.ids import uuid7
from src.modules.ab_tests.models import AbTest, AbTestVariant
from src.modules.ab_tests.services.storage import StoredImage
from src.modules.ab_tests.services.thumbnails import THUMBNAIL_CONTENT_TYPE, thumbnail_key
from src.modules.ab_tests.services.variants import VariantCatalogService

WORKSPACE_ID = uuid7()
TEST_ID = uuid7()
VARIANT_ID = uuid7()
IMAGE_PATH = f"{TEST_ID}/abc.png"


def _png(size: tuple[int, int] = (1600, 1200)) -> bytes:
    """A PNG big enough that shrinking it is visible in the byte count."""
    buffer = io.BytesIO()
    Image.new("RGB", size, (90, 120, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeStore:
    """A media store in a dict, recording what was read and written."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.reads: list[str] = []
        self.puts: list[str] = []
        self.put_fails = False

    async def read(self, relative_path: str) -> bytes:
        self.reads.append(relative_path)
        try:
            return self.objects[relative_path]
        except KeyError as exc:
            raise FileNotFoundError(relative_path) from exc

    async def put(self, *, relative_path: str, content: bytes, content_type: str) -> None:
        if self.put_fails:
            raise RuntimeError("bucket refused the write")
        self.puts.append(relative_path)
        self.objects[relative_path] = content

    async def save(self, *, content: bytes, content_type: str, test_id: uuid.UUID) -> StoredImage:
        self.objects[IMAGE_PATH] = content
        return StoredImage(relative_path=IMAGE_PATH, sha256="0" * 64, size_bytes=len(content))


class _FakeTests:
    """Resolves the one test these cases use."""

    async def get(self, *, workspace_id: uuid.UUID, test_id: uuid.UUID) -> AbTest | None:
        if workspace_id != WORKSPACE_ID or test_id != TEST_ID:
            return None
        test = AbTest(id=TEST_ID, workspace_id=WORKSPACE_ID, nm_id=995716075, name="Тест")
        test.variants = []
        return test


class _FakeVariants:
    """Resolves the one variant these cases use.

    `get_scoped` carries the tenancy guard in SQL, so this fake can only stand
    in for its shape; that the JOIN actually refuses another workspace's variant
    is proved against a real database in
    tests/integration/ab_tests/test_ab_test_repos.py.
    """

    async def get_scoped(
        self, *, workspace_id: uuid.UUID, test_id: uuid.UUID, variant_id: uuid.UUID
    ) -> AbTestVariant | None:
        if workspace_id != WORKSPACE_ID or test_id != TEST_ID:
            return None
        return await self.get(test_id=test_id, variant_id=variant_id)

    async def count_for_test(self, *, test_id: uuid.UUID) -> int:
        return 0

    async def add(self, **kwargs: object) -> AbTestVariant:
        return await self.get(test_id=TEST_ID, variant_id=VARIANT_ID)  # type: ignore[return-value]

    async def get(self, *, test_id: uuid.UUID, variant_id: uuid.UUID) -> AbTestVariant | None:
        if variant_id != VARIANT_ID:
            return None
        return AbTestVariant(
            id=VARIANT_ID,
            test_id=TEST_ID,
            position=1,
            image_path=IMAGE_PATH,
            image_sha256="0" * 64,
            content_type="image/png",
            original_filename="photo.png",
        )


def _service(store: _FakeStore) -> VariantCatalogService:
    """The real service over fakes."""
    return VariantCatalogService(
        tests=_FakeTests(),  # type: ignore[arg-type]
        variants=_FakeVariants(),  # type: ignore[arg-type]
        stats=object(),  # type: ignore[arg-type]
        media_store=store,  # type: ignore[arg-type]
    )


async def _read(service: VariantCatalogService, *, thumbnail: bool) -> tuple[bytes, str]:
    return await service.read_variant_image(
        workspace_id=WORKSPACE_ID,
        test_id=TEST_ID,
        variant_id=VARIANT_ID,
        thumbnail=thumbnail,
    )


async def test_the_thumbnail_is_derived_once_and_reused() -> None:
    """The second request reads the cached object and decodes nothing."""
    original = _png()
    store = _FakeStore({IMAGE_PATH: original})
    service = _service(store)

    first, content_type = await _read(service, thumbnail=True)
    store.reads.clear()
    second, _ = await _read(service, thumbnail=True)

    assert content_type == THUMBNAIL_CONTENT_TYPE
    assert first == second
    assert len(first) < len(original) / 5
    assert store.puts == [thumbnail_key(IMAGE_PATH)]
    # Second time round: the derivative, and never the original.
    assert store.reads == [thumbnail_key(IMAGE_PATH)]


async def test_the_full_size_is_still_the_stored_original() -> None:
    """WB gets the seller's own file, so the route must be able to serve it."""
    original = _png()
    store = _FakeStore({IMAGE_PATH: original})

    content, content_type = await _read(_service(store), thumbnail=False)

    assert content == original
    assert content_type == "image/png"
    assert store.puts == []


async def test_an_image_that_cannot_be_resized_is_served_whole() -> None:
    """Slow beats absent: on these screens the picture IS the row."""
    store = _FakeStore({IMAGE_PATH: b"this is not a PNG"})

    content, _ = await _read(_service(store), thumbnail=True)

    assert content == b"this is not a PNG"


async def test_a_bucket_that_refuses_the_cache_write_still_answers() -> None:
    """The derivative is worth serving even when it cannot be kept."""
    store = _FakeStore({IMAGE_PATH: _png()})
    store.put_fails = True

    _, content_type = await _read(_service(store), thumbnail=True)

    assert content_type == THUMBNAIL_CONTENT_TYPE
    assert store.puts == []


async def test_a_variant_of_another_workspace_is_absent_rather_than_forbidden() -> None:
    """The thumbnail path must not become a way around the tenancy guard."""
    service = _service(_FakeStore({IMAGE_PATH: _png()}))

    with pytest.raises(NotFoundError):
        await service.read_variant_image(
            workspace_id=uuid7(),
            test_id=TEST_ID,
            variant_id=VARIANT_ID,
            thumbnail=True,
        )


async def test_an_upload_is_sized_down_before_anyone_asks_for_it() -> None:
    """The derivation happens on upload, not on the first page view.

    It costs about as long as the upload itself, and a reader opening a test
    with ten photos would otherwise pay all ten at once — which is the slow
    first load the thumbnails exist to remove. The seller is already waiting on
    the upload, so that is where the time belongs.
    """
    store = _FakeStore({})
    service = _service(store)

    await service.add_variant(
        workspace_id=WORKSPACE_ID,
        test_id=TEST_ID,
        content=_png(),
        content_type="image/png",
        filename="photo.png",
    )

    assert store.puts == [thumbnail_key(IMAGE_PATH)]


async def test_an_upload_whose_thumbnail_fails_is_still_accepted() -> None:
    """Losing the photo over a failed resize would be the worse trade."""
    store = _FakeStore({})
    store.put_fails = True
    service = _service(store)

    variant = await service.add_variant(
        workspace_id=WORKSPACE_ID,
        test_id=TEST_ID,
        content=_png(),
        content_type="image/png",
        filename="photo.png",
    )

    assert variant.id == VARIANT_ID
    assert store.objects[IMAGE_PATH]
