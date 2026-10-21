"""Where variant photos are kept, and which store a deployment gets.

Two things are pinned here. The selection is the first and the connection
reuse is the second: a client opened per call cost a TLS handshake per image —
0.259 s against 0.071 s on a warm one, as measured.

Reuse is **opt-in**, and that is the part worth a test. The api runs one loop for
the life of the process and can hold a connection; a Celery task runs on a loop it
closes when it returns, and a socket pooled across that boundary is the failure
`src.core.tasks` was written for. A default that quietly changed for the worker
would cost a night's harvest, as it twice has.

The selection is the part that matters. A deployed api and worker do not share a
filesystem: the upload lands in one container and the rotation reads the bytes
back in the other, so a local directory means the poller cannot find the photo
it is supposed to install. That failure is invisible until the second rotation,
because the first photo is installed synchronously by the api itself.
"""

from __future__ import annotations

import asyncio
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


class _FakeS3Session:
    """Stands in for `aioboto3.Session`, counting the clients it is asked for."""

    def __init__(self, fail_first: bool = False) -> None:
        self.opened = 0
        self.closed = 0
        self.fail_first = fail_first

    def client(self, *args: object, **kwargs: object) -> _FakeClientManager:
        return _FakeClientManager(self)


class _FakeClientManager:
    """The async context manager `Session.client()` returns."""

    def __init__(self, session: _FakeS3Session) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        if self._session.fail_first and self._session.opened == 0:
            self._session.opened += 1
            raise ConnectionError("the endpoint was not answering")
        self._session.opened += 1
        return object()

    async def __aexit__(self, *exc: object) -> None:
        self._session.closed += 1


def _store(session: _FakeS3Session, *, reuse: bool = True) -> S3MediaStore:
    """An S3 store whose session is the fake above."""
    store = S3MediaStore(
        bucket="photos",
        prefix="ab",
        endpoint_url="https://example.invalid",
        region="ru-1",
        access_key="key",
        secret_key="secret",
        reuse_connections=reuse,
    )
    store._session = session  # the seam this test exists for
    return store


async def test_one_client_serves_every_call_on_a_loop() -> None:
    """Nine images on a page must not mean nine TLS handshakes."""
    session = _FakeS3Session()
    store = _store(session)

    async with store._connection() as first, store._connection() as second:
        assert first is second
    assert session.opened == 1


async def test_concurrent_callers_open_one_client_between_them() -> None:
    """The detail page asks for six photos at once, and they all arrive here
    together — each seeing no client yet."""
    session = _FakeS3Session()
    store = _store(session)

    clients = await asyncio.gather(*(store._held_client() for _ in range(6)))

    assert len({id(client) for client in clients}) == 1
    assert session.opened == 1


async def test_without_reuse_every_call_opens_and_closes_its_own_client() -> None:
    """What the worker gets, and must keep getting.

    A Celery task drives its body through its own `asyncio.run` and closes that
    loop on the way out. A client pooled across that boundary hands the next
    task a socket whose transport is gone — which is exactly the failure
    `src.core.tasks` drains the database and Redis pools to avoid.
    """
    session = _FakeS3Session()
    store = _store(session, reuse=False)

    async with store._connection():
        pass
    async with store._connection():
        pass

    assert session.opened == 2
    assert session.closed == 2
    assert store._clients == {}


async def test_a_held_client_is_closed_on_shutdown() -> None:
    """`aclose` is what the app's lifespan calls, and it has to actually close.

    Held open and never exited, the connection outlives the loop that owns it
    and aiohttp complains about it at interpreter exit — noise that reads like
    a leak because it is one.
    """
    session = _FakeS3Session()
    store = _store(session)

    async with store._connection():
        pass
    await store.aclose()

    assert session.closed == 1
    assert store._clients == {}


async def test_closing_a_store_that_never_opened_one_is_quiet() -> None:
    """Most processes shut down without having served a photo."""
    store = _store(_FakeS3Session())

    await store.aclose()


async def test_a_failed_open_is_not_remembered() -> None:
    """One bad moment must not leave the bucket broken for the whole process."""
    session = _FakeS3Session(fail_first=True)
    store = _store(session)

    with pytest.raises(ConnectionError):
        await store._held_client()
    client = await store._held_client()

    assert client is not None
