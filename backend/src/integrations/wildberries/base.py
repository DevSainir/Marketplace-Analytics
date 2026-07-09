"""Shared async HTTP plumbing for WildBerries API surfaces.

Every WB API family (Analytics, Advertising, ...) authenticates with its own
bearer token but shares identical transport behaviour: JSON encoding, timeout
handling, and uniform error translation into :class:`IntegrationError`.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import httpx

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger

logger = get_logger(__name__)

# HTTP statuses worth retrying: 429 (rate limited) and transient 5xx.
_RETRIABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Absolute ceiling on honouring a server-provided Retry-After. The server's
# demand is respected even beyond the exponential-backoff cap (WB's
# advertising limiter regularly asks for 60s+), but a pathological header
# must not park a task for hours.
_RETRY_AFTER_CEILING_SECONDS: float = 900.0


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


class BaseWBClient:
    """Async base client wrapping a single :class:`httpx.AsyncClient`.

    Subclasses supply a base URL and the API token for their surface. The
    client is an async context manager so callers deterministically close the
    underlying connection pool::

        async with WBAnalyticsClient(...) as client:
            data = await client.fetch_sales_funnel(...)
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float,
        max_retries: int = 4,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 60.0,
    ) -> None:
        """Configure the client transport and retry policy.

        Args:
            base_url: Root URL for this WB API surface.
            token: Bearer token authorising requests to this surface.
            timeout: Per-request timeout in seconds.
            max_retries: Additional attempts after the first on a retriable
                failure (429 / transient 5xx / transport error).
            backoff_base_seconds: Base for the exponential backoff sequence
                ``base * 2**(attempt - 1)``.
            backoff_max_seconds: Upper bound applied to any single backoff wait.
        """
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout),
            headers={
                "Authorization": token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> Self:
        """Enter the async context, returning the live client."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the underlying HTTP connection pool on context exit."""
        await self.aclose()

    async def aclose(self) -> None:
        """Explicitly close the underlying async HTTP client."""
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Perform an async request and return the decoded JSON payload.

        Args:
            method: HTTP verb (``GET`` / ``POST``).
            path: Path appended to the client's base URL.
            params: Optional query-string parameters.
            json_body: Optional JSON request body.

        Retries retriable failures (HTTP 429 / transient 5xx / transport
        errors) up to ``max_retries`` times with exponential backoff, honouring
        a ``Retry-After`` header when WB supplies one. Non-retriable 4xx errors
        (e.g. 400/401) fail fast.

        Returns:
            The deserialized JSON response (``dict`` or ``list``).

        Raises:
            IntegrationError: On a non-retriable error, or once retries are
                exhausted.
        """
        last_exc: httpx.HTTPError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, path, params=params, json=json_body)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                if status not in _RETRIABLE_STATUSES or attempt == self._max_retries:
                    logger.warning("WB API returned %s for %s %s", status, method, path)
                    raise IntegrationError(f"WildBerries API error {status} on {path}.") from exc
                delay = self._retry_delay(attempt, exc.response)
                logger.warning(
                    "WB API %s on %s %s; retry %d/%d in %.1fs",
                    status,
                    method,
                    path,
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == self._max_retries:
                    logger.warning("WB API transport error for %s %s: %s", method, path, exc)
                    raise IntegrationError(f"WildBerries API unreachable on {path}.") from exc
                delay = self._retry_delay(attempt, None)
                logger.warning(
                    "WB API transport error on %s %s; retry %d/%d in %.1fs",
                    method,
                    path,
                    attempt + 1,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)

        # Unreachable: the loop either returns or raises. Guard for type safety.
        raise IntegrationError(f"WildBerries API request failed on {path}.") from last_exc

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Compute the backoff delay before the next retry.

        Prefers the server's ``Retry-After`` header when present (both
        delta-seconds and HTTP-date forms), honouring it even beyond the
        exponential-backoff cap — retrying before the server's stated window
        just burns an attempt against the same limiter. Otherwise falls back
        to exponential backoff ``base * 2**attempt``.

        Args:
            attempt: Zero-based index of the attempt that just failed.
            response: The failed response, if any (for ``Retry-After``).

        Returns:
            The number of seconds to wait before retrying.
        """
        if response is not None:
            header = response.headers.get("Retry-After")
            if header:
                parsed = _parse_retry_after(header)
                if parsed is not None:
                    return min(parsed, _RETRY_AFTER_CEILING_SECONDS)
        return min(self._backoff_base * (2.0**attempt), self._backoff_max)
