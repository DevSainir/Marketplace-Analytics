"""Reading an upload must stop at the ceiling, not measure it afterwards.

Both upload routes used to do ``data = await file.read()`` and check
``len(data)`` on the next line. That check cannot protect anything: the bytes
are already in the process. On a 512 MB container one oversized upload is an
OOM kill, and the kill takes every other in-flight request on that worker with it.

What these pin is the difference between the two: the refusal happens while
reading, so the peak is the ceiling rather than the file.
"""

from __future__ import annotations

import io

import pytest
from fastapi import UploadFile

from src.core.exceptions import ValidationError
from src.core.uploads import read_capped

TOO_LARGE = "The file is too large."


def _upload(payload: bytes) -> UploadFile:
    """Wrap bytes in an ``UploadFile`` the way Starlette hands one to a route."""
    return UploadFile(filename="sheet.xlsx", file=io.BytesIO(payload))


async def test_a_file_within_the_ceiling_reads_back_whole() -> None:
    """The ordinary case must be byte-for-byte unchanged."""
    payload = b"x" * 4096

    data = await read_capped(_upload(payload), max_bytes=8192, too_large=TOO_LARGE)

    assert data == payload


async def test_a_file_exactly_at_the_ceiling_is_accepted() -> None:
    """The limit is inclusive, so a file at the documented size still works.

    An off-by-one here would reject the 32 MB image the A/B upload advertises.
    """
    payload = b"x" * 8192

    data = await read_capped(_upload(payload), max_bytes=8192, too_large=TOO_LARGE)

    assert len(data) == 8192


async def test_one_byte_over_the_ceiling_is_refused() -> None:
    """The first byte past the limit ends the read."""
    payload = b"x" * 8193

    with pytest.raises(ValidationError, match="too large"):
        await read_capped(_upload(payload), max_bytes=8192, too_large=TOO_LARGE)


async def test_the_refusal_does_not_read_the_whole_file() -> None:
    """The point of the change: a huge upload is refused having held the cap.

    Asserted through the stream position — a reader that had consumed the whole
    file to measure it would leave nothing behind, which is exactly the
    behaviour that made the old check useless.
    """
    payload = b"x" * (4 * 1024 * 1024)
    source = io.BytesIO(payload)
    upload = UploadFile(filename="big.bin", file=source)

    with pytest.raises(ValidationError):
        await read_capped(upload, max_bytes=1024, too_large=TOO_LARGE)

    assert source.tell() < len(payload)


async def test_an_empty_upload_reads_as_empty() -> None:
    """No bytes is not an error here; the routes report it in their own words."""
    data = await read_capped(_upload(b""), max_bytes=8192, too_large=TOO_LARGE)

    assert data == b""
