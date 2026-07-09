"""Time-ordered UUIDv7 generation.

PostgreSQL B-Tree indexes degrade under random UUIDv4 primary keys because
inserts scatter across the whole index. UUIDv7 embeds a millisecond Unix
timestamp in its most-significant bits, so freshly minted keys append to the
right edge of the index (great locality) while remaining non-enumerable.

The implementation follows the layout from RFC 9562 §5.7.
"""

from __future__ import annotations

import os
import time
import uuid

# UUIDv7 bit-field widths used to assemble the 128-bit integer.
_VERSION: int = 0x7
_VARIANT: int = 0b10


def uuid7() -> uuid.UUID:
    """Return a fresh, time-ordered UUID version 7.

    Layout (128 bits):
        * 48 bits — Unix timestamp in milliseconds.
        * 4 bits  — version (0b0111).
        * 12 bits — sub-millisecond random / sequence entropy.
        * 2 bits  — variant (0b10).
        * 62 bits — random entropy.

    Returns:
        A :class:`uuid.UUID` instance whose lexical ordering matches creation
        time to millisecond resolution.
    """
    unix_ms: int = time.time_ns() // 1_000_000
    rand_a: int = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b: int = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)

    value: int = (unix_ms & ((1 << 48) - 1)) << 80
    value |= _VERSION << 76
    value |= rand_a << 64
    value |= _VARIANT << 62
    value |= rand_b

    return uuid.UUID(int=value)
