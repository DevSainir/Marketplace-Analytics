"""What a failed WB response says about when to try again — and what to log.

Split out of ``base`` on the retry ladder's own responsibility: "how long did
the server tell us to wait" is a question about HTTP headers, answered the same
way for every surface, and it was the half of that module with no dependency on
the client at all.

The ceiling is the part worth reading before changing anything here. WB's
advertising limiter routinely asks for a minute or more and that demand is
honoured past the exponential cap, because the server knows its own budget
better than our backoff does — but a pathological header must not be able to
park a Celery task for hours.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

#: Redacts ``user:password@`` credentials from a proxy URL before logging.
_CREDENTIALS_RE = re.compile(r"//[^/@\s]+@")


def scrub_credentials(text: str) -> str:
    """Strip any ``user:pass@`` credentials from a string before it is logged.

    Lives here rather than in one client because any surface reached through a
    forward proxy can surface the tunnel's URL — credentials included — inside a
    transport error's own message.
    """
    return _CREDENTIALS_RE.sub("//***@", text)


# HTTP statuses worth retrying: 429 (rate limited) and transient 5xx.
_RETRIABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Absolute ceiling on honouring a server-provided Retry-After. The server's
# demand is respected even beyond the exponential-backoff cap (WB's
# advertising limiter regularly asks for 60s+), but a pathological header
# must not park a task for hours.
_RETRY_AFTER_CEILING_SECONDS: float = 900.0


def _server_demanded_wait(response: httpx.Response) -> float | None:
    """The wait the server demands before the next request, in seconds.

    Checks the standard ``Retry-After`` first, then WB's own
    ``X-Ratelimit-Retry`` (used by the statistics surface, in delta-seconds).

    Args:
        response: The failed (429/5xx) response.

    Returns:
        Seconds to wait, or ``None`` when the server named no wait.
    """
    header = response.headers.get("Retry-After")
    if header:
        parsed = _parse_retry_after(header)
        if parsed is not None:
            return parsed
    wb_retry = response.headers.get("X-Ratelimit-Retry")
    if wb_retry and wb_retry.strip().isdigit():
        return float(wb_retry.strip())
    return None


def _parse_retry_after(value: str) -> float | None:
    """Parse a ``Retry-After`` header into seconds.

    Supports both RFC 9110 forms: delta-seconds (``"120"``) and HTTP-date
    (``"Wed, 21 Oct 2026 07:28:00 GMT"``).

    Args:
        value: The raw header value.

    Returns:
        Seconds to wait (>= 0), or ``None`` when the value is unparseable.
    """
    stripped = value.strip()
    if stripped.isdigit():
        return float(stripped)
    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    return max(0.0, (target - datetime.now(UTC)).total_seconds())
