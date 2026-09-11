"""Where a variant's original bytes live between the upload and the rotation.

The two ends of that sentence are in **different containers**. A photo is
uploaded through the api and read back by the poller in the worker, which is why
this is object storage rather than a directory: a container-local path means the
worker cannot find what the api wrote, so the first photo would go up (the api
installs it synchronously) and every rotation after it would fail on a missing
file. A named volume would fix that one and still lose everything on a rebuild,
while the photos have to outlive a test that runs for days.

The local implementation is kept for tests and for a developer with no bucket.
It is deliberately not a deployment option, and :func:`build_media_store` says
so by picking S3 whenever a bucket is configured.
"""

from __future__ import annotations

import hashlib
import uuid
from asyncio import AbstractEventLoop, Task, get_running_loop
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import aioboto3

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger

logger = get_logger(__name__)

_SUFFIX_BY_TYPE: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
}


@dataclass(frozen=True)
class StoredImage:
    """An image written to the media store."""

    #: Key or path, as stored on the variant row. Contains the content digest,
    #: so the same picture uploaded twice occupies one object.
    relative_path: str
    sha256: str
    size_bytes: int


class MediaStore(Protocol):
    """What the module needs from wherever the originals are kept."""

    async def save(
        self, *, content: bytes, content_type: str, test_id: uuid.UUID
    ) -> StoredImage: ...

    async def put(self, *, relative_path: str, content: bytes, content_type: str) -> None: ...

    async def read(self, relative_path: str) -> bytes: ...

    async def delete(self, relative_path: str) -> None: ...


def _key_for(content: bytes, *, content_type: str, test_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(digest, relative key)`` for one image.

    One directory (or prefix) per test keeps the store browsable when an upload
    has to be inspected by hand, and the digest makes the key content-addressed:
    re-uploading the same picture cannot produce a second object.
    """
    digest = hashlib.sha256(content).hexdigest()
    suffix = _SUFFIX_BY_TYPE.get(content_type, ".bin")
    return digest, f"{test_id}/{digest}{suffix}"


class LocalMediaStore:
    """Originals under a directory. For tests and single-process development.

    Not for a deployment: the api and the worker do not share a filesystem, so
    a photo written here is invisible to the rotation that has to read it back.
    """

    def __init__(self, root: Path) -> None:
        """Bind the store to its root directory.

        Args:
            root: Directory holding every variant image.
        """
        self._root = root

    async def save(self, *, content: bytes, content_type: str, test_id: uuid.UUID) -> StoredImage:
        """Write an uploaded image and return its identity.

        Args:
            content: Raw image bytes, already validated.
            content_type: MIME type, used to pick the file suffix.
            test_id: Owning test.

        Returns:
            The stored path, digest and size.
        """
        digest, relative = _key_for(content, content_type=content_type, test_id=test_id)
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return StoredImage(relative_path=relative, sha256=digest, size_bytes=len(content))

    async def put(self, *, relative_path: str, content: bytes, content_type: str) -> None:
        """Write bytes at a key the CALLER chose.

        The counterpart to :meth:`save`, which derives the key from the content.
        A derivative — a thumbnail — has to be filed under a name derived from
        its original's, or nothing can find it again without a second column.

        Args:
            relative_path: Where to write, relative to the root.
            content: The bytes.
            content_type: Ignored here; a file has no metadata.
        """
        target = self._root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def read(self, relative_path: str) -> bytes:
        """Return the stored bytes of one image.

        Args:
            relative_path: Path as stored on the variant row.

        Returns:
            The image bytes.

        Raises:
            FileNotFoundError: If the file is missing.
        """
        return (self._root / relative_path).read_bytes()

    async def delete(self, relative_path: str) -> None:
        """Remove a stored image, tolerating one that is already gone.

        Args:
            relative_path: Path as stored on the variant row.
        """
        (self._root / relative_path).unlink(missing_ok=True)


class S3MediaStore:
    """Originals in an S3-compatible bucket, shared by every container.

    ``reuse_connections`` decides whether the client is held open, and it is off
    by default because holding one is only safe where the event loop outlives
    the request. Timed against production:

        read() with a new client   22.9 KB   0.259 s
        opening the client itself            0.005 s
        get_object on a reused client        0.071 s

    The client object is nearly free; the **connection** is not. Nine images on
    one page spent about 1.7 seconds doing nothing but shaking hands, which is
    why the api turns reuse on — it runs one loop for the life of the process
    and closes the client from the app's own shutdown.

    **The worker leaves it off, deliberately.** Every Celery task drives its body
    through its own :func:`asyncio.run` and closes that loop afterwards; a
    pooled socket left behind belongs to a loop that no longer exists, and the
    next task dies on it with «Event loop is closed». :mod:`src.core.tasks`
    exists because that has happened twice, to the SQLAlchemy engine and to the
    Redis pool, and each time it cost a whole night's harvest. The worker reads
    a photo once per swap, so reuse would buy it a fraction of a second in
    exchange for that.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        reuse_connections: bool = False,
    ) -> None:
        """Configure the bucket this store writes to.

        Args:
            bucket: Bucket name.
            prefix: Key prefix inside it. Object storage has no directories —
                the prefix appears on the first PUT, so nothing has to be
                created in advance.
            endpoint_url: S3-compatible endpoint.
            region: Region name the endpoint expects.
            access_key: Access key id.
            secret_key: Secret access key.
            reuse_connections: Hold one client open per event loop. Only for a
                caller whose loop outlives the request — see the class docstring.
        """
        self._reuse = reuse_connections
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._session = aioboto3.Session()
        # loop -> the task that opens (and then holds) that loop's client, and
        # the manager it was entered through so shutdown can exit it. A task
        # rather than the client itself so that concurrent callers on one loop
        # await the same creation instead of opening a client each: the detail
        # page asks for six images at once, and the first thing they all do is
        # arrive here together.
        self._clients: dict[AbstractEventLoop, Task[Any]] = {}
        self._managers: dict[AbstractEventLoop, Any] = {}

    def _new_client(self) -> Any:
        """The async context manager for one fresh client."""
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            region_name=self._region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
        )

    async def _open(self, loop: AbstractEventLoop) -> Any:
        """Enter a client's context, keeping the manager so it can be exited."""
        manager = self._new_client()
        client = await manager.__aenter__()
        self._managers[loop] = manager
        return client

    async def _held_client(self) -> Any:
        """Return this event loop's client, opening it the first time.

        Returns:
            An aiobotocore S3 client, safe to use from several coroutines at
            once — the connection pool behind it is what makes that worth doing.
        """
        loop = get_running_loop()
        opening = self._clients.get(loop)
        if opening is None:
            # `create_task` is synchronous, so two callers on this loop cannot
            # both see None and both open a client.
            opening = loop.create_task(self._open(loop))
            self._clients[loop] = opening
        try:
            return await opening
        except Exception:
            # A failed open must not be cached, or the bucket stays broken for
            # the life of the process after one bad moment.
            self._clients.pop(loop, None)
            self._managers.pop(loop, None)
            raise

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Any]:
        """Yield a client for one operation, held open or not.

        One shape for both policies, so no call site has to remember which is in
        force.

        Yields:
            An aiobotocore S3 client.
        """
        if not self._reuse:
            async with self._new_client() as client:
                yield client
            return
        yield await self._held_client()

    async def aclose(self) -> None:
        """Close the client held for the CURRENT loop, if there is one.

        Called from the app's shutdown, which is the only place that knows the
        loop is about to end. Closing is best-effort: a socket the endpoint has
        already dropped raises here, and failing a shutdown over it would turn a
        clean exit into a stack trace.
        """
        loop = get_running_loop()
        self._clients.pop(loop, None)
        manager = self._managers.pop(loop, None)
        if manager is None:
            return
        try:
            await manager.__aexit__(None, None, None)
        except Exception as exc:  # pragma: no cover - endpoint-level failure
            logger.info("ab_tests: closing the media client raised: %s", exc)

    def _object_key(self, relative_path: str) -> str:
        """Full object key for a path as stored on the variant row."""
        return f"{self._prefix}/{relative_path}" if self._prefix else relative_path

    async def save(self, *, content: bytes, content_type: str, test_id: uuid.UUID) -> StoredImage:
        """Upload an image and return its identity.

        Args:
            content: Raw image bytes, already validated.
            content_type: MIME type, stored on the object so the image route can
                serve it back without guessing.
            test_id: Owning test.

        Returns:
            The stored key (relative to the prefix), digest and size.

        Raises:
            IntegrationError: If the bucket refuses the write.
        """
        digest, relative = _key_for(content, content_type=content_type, test_id=test_id)
        try:
            async with self._connection() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=self._object_key(relative),
                    Body=content,
                    ContentType=content_type,
                )
        except Exception as exc:
            logger.warning("ab_tests: media upload failed for %s: %s", relative, exc)
            raise IntegrationError("Не удалось сохранить изображение в хранилище.") from exc
        return StoredImage(relative_path=relative, sha256=digest, size_bytes=len(content))

    async def put(self, *, relative_path: str, content: bytes, content_type: str) -> None:
        """Write bytes at a key the CALLER chose.

        The counterpart to :meth:`save`, which derives the key from the content.
        A derivative — a thumbnail — has to be filed under a name derived from
        its original's, or nothing can find it again without a second column.

        Args:
            relative_path: Key to write, relative to the prefix.
            content: The bytes.
            content_type: Stored on the object, so the image route serves it
                back without guessing.

        Raises:
            IntegrationError: If the bucket refuses the write.
        """
        try:
            async with self._connection() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=self._object_key(relative_path),
                    Body=content,
                    ContentType=content_type,
                )
        except Exception as exc:
            logger.warning("ab_tests: media put failed for %s: %s", relative_path, exc)
            raise IntegrationError("Не удалось сохранить изображение в хранилище.") from exc

    async def read(self, relative_path: str) -> bytes:
        """Return the stored bytes of one image.

        Args:
            relative_path: Key as stored on the variant row.

        Returns:
            The image bytes.

        Raises:
            FileNotFoundError: If the object is absent — the same failure the
                local store raises, so callers handle one shape.
            IntegrationError: If the bucket is unreachable.
        """
        try:
            async with self._connection() as client:
                response = await client.get_object(
                    Bucket=self._bucket, Key=self._object_key(relative_path)
                )
                body: bytes = await response["Body"].read()
                return body
        except Exception as exc:
            if "NoSuchKey" in repr(exc) or "404" in repr(exc):
                raise FileNotFoundError(relative_path) from exc
            logger.warning("ab_tests: media read failed for %s: %s", relative_path, exc)
            raise IntegrationError("Не удалось прочитать изображение из хранилища.") from exc

    async def delete(self, relative_path: str) -> None:
        """Remove an object, tolerating one that is already gone.

        Args:
            relative_path: Key as stored on the variant row.
        """
        try:
            async with self._connection() as client:
                await client.delete_object(Bucket=self._bucket, Key=self._object_key(relative_path))
        except Exception as exc:
            logger.warning("ab_tests: media delete failed for %s: %s", relative_path, exc)


def build_media_store(settings: Settings, *, reuse_connections: bool = False) -> MediaStore:
    """Return the store this deployment should use.

    Args:
        settings: Bucket configuration; an empty bucket name selects the local
            directory, which is what tests and a developer without credentials
            get.
        reuse_connections: Hold one S3 client open per event loop. Safe only for
            a caller whose loop outlives the request — the api, not a Celery
            task. See :class:`S3MediaStore`.

    Returns:
        An S3-backed store when a bucket is configured, else the local one.
    """
    if not settings.ab_tests_s3_bucket:
        return LocalMediaStore(Path(settings.ab_tests_media_dir))
    return S3MediaStore(
        bucket=settings.ab_tests_s3_bucket,
        prefix=settings.ab_tests_media_prefix,
        endpoint_url=settings.ab_tests_s3_endpoint_url,
        region=settings.ab_tests_s3_region,
        access_key=settings.ab_tests_s3_access_key,
        secret_key=settings.ab_tests_s3_secret_key,
        reuse_connections=reuse_connections,
    )
