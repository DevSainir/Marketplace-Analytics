"""Where variant photos are kept, and which store a deployment gets.

The selection is the part that matters. A deployed api and worker do not share a
filesystem: the upload lands in one container and the rotation reads the bytes
back in the other, so a local directory means the poller cannot find the photo
it is supposed to install. That failure is invisible until the second rotation,
because the first photo is installed synchronously by the api itself.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from src.core.config import Settings
from src.modules.ab_tests.services.storage import (
    LocalMediaStore,
    S3MediaStore,
    build_media_store,
)

TEST_ID = uuid.UUID("00000000-0000-7000-8000-00000000000a")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 512


def _settings(**overrides: object) -> Settings:
    """Settings with the storage fields overridden."""
    base = Settings()
    for key, value in overrides.items():
        object.__setattr__(base, key, value)
    return base


def test_a_configured_bucket_selects_object_storage() -> None:
    """With a bucket, photos go where both containers can read them."""
    store = build_media_store(_settings(ab_tests_s3_bucket="photos"))

    assert isinstance(store, S3MediaStore)


def test_no_bucket_falls_back_to_a_local_directory() -> None:
    """Tests and a developer without credentials still get a working store.

    This is the branch that must never be what a deployment runs: it is chosen
    only when no bucket is configured at all.
    """
    store = build_media_store(_settings(ab_tests_s3_bucket=""))

    assert isinstance(store, LocalMediaStore)


async def test_the_key_is_content_addressed(tmp_path: Path) -> None:
    """The same picture uploaded twice occupies one key.

    The digest is also what ties a photo to the metrics it earned, so the key
    and the evidence are the same fact.
    """
    store = LocalMediaStore(tmp_path)

    first = await store.save(content=JPEG, content_type="image/jpeg", test_id=TEST_ID)
    second = await store.save(content=JPEG, content_type="image/jpeg", test_id=TEST_ID)

    assert first.relative_path == second.relative_path
    assert first.sha256 in first.relative_path
    assert first.relative_path.startswith(f"{TEST_ID}/")


async def test_bytes_survive_the_round_trip(tmp_path: Path) -> None:
    """What WB receives must be what the user uploaded, byte for byte."""
    store = LocalMediaStore(tmp_path)
    original = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4

    stored = await store.save(content=original, content_type="image/jpeg", test_id=TEST_ID)

    assert await store.read(stored.relative_path) == original


async def test_a_missing_image_raises_not_found(tmp_path: Path) -> None:
    """Both stores report an absent object the same way, so callers handle one shape."""
    store = LocalMediaStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        await store.read("nope/missing.jpg")


async def test_deleting_twice_is_not_an_error(tmp_path: Path) -> None:
    """Cleanup runs after a variant is removed and must not fail on a retry."""
    store = LocalMediaStore(tmp_path)
    stored = await store.save(content=JPEG, content_type="image/jpeg", test_id=TEST_ID)

    await store.delete(stored.relative_path)
    await store.delete(stored.relative_path)

    with pytest.raises(FileNotFoundError):
        await store.read(stored.relative_path)
