"""Reading uploaded files without trusting their declared size.

Both upload routes used to call ``await file.read()`` and check ``len(data)``
afterwards, which is a check that happens too late to protect anything: the
whole body is in the process's memory by the time it runs. On a container
limited to 512 MB, a single large upload is an OOM kill of the API — and the
kill takes every in-flight request on that worker with it.

Reading in bounded chunks and stopping at the ceiling costs the same for a
legitimate file and refuses an oversized one having held ``max_bytes`` plus one
chunk. Starlette has already spooled the body (to a temporary file above ~1 MB)
before a handler runs, so this bounds **memory**; the bound on what may be
uploaded at all is nginx's ``client_max_body_size``, and the two are meant to be
read together.
"""

from __future__ import annotations

from fastapi import UploadFile

from src.core.exceptions import ValidationError

#: Read granularity. Large enough that a 32 MB image is ~64 reads rather than
#: thousands, small enough that the overshoot past the ceiling is negligible.
_CHUNK_BYTES = 512 * 1024


async def read_capped(file: UploadFile, *, max_bytes: int, too_large: str) -> bytes:
    """Read an upload into memory, refusing it once it passes ``max_bytes``.

    Args:
        file: The uploaded file.
        max_bytes: The largest body this endpoint accepts.
        too_large: Message for the caller when the file exceeds it. Written for
            a user, so it must not echo the size back as proof of anything.

    Returns:
        The complete contents, which are guaranteed to be ``max_bytes`` or
        fewer.

    Raises:
        ValidationError: When the upload exceeds ``max_bytes``, raised as soon
            as the ceiling is passed rather than after the whole body is held.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError(too_large)
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ["read_capped"]
