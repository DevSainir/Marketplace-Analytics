"""Shared async HTTP plumbing for WildBerries API surfaces.

Every WB API family (Analytics, Advertising, ...) authenticates with its own
bearer token but shares identical transport behaviour: JSON encoding, timeout
handling, and uniform error translation into :class:`IntegrationError`.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import TracebackType
from typing import Any, Self

import httpx

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.observability.metrics import WB_API_DURATION, WB_API_REQUESTS
from src.integrations.wildberries.endpoints import endpoint_label
from src.integrations.wildberries.rate_limit import NullRateGate, RateGate

logger = get_logger(__name__)

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


class BaseWBClient:
    """Async base client wrapping a single :class:`httpx.AsyncClient`.

    Subclasses supply a base URL and the API token for their surface. The
    client is an async context manager so callers deterministically close the
    underlying connection pool::

        async with WBAnalyticsClient(...) as client:
            data = await client.fetch_sales_funnel(...)
    """

    #: The name this surface appears under in metrics. Derived from the class
    #: name when left unset — ``WBAnalyticsClient`` becomes ``analytics`` — so
    #: a new client is instrumented the moment it exists rather than the moment
    #: somebody remembers to label it. Set it explicitly on a subclass whose
    #: class name is not the name a dashboard should show.
    WB_SURFACE: str | None = None

    @classmethod
    def surface(cls) -> str:
        """Return this client's metric label for the WB surface it talks to."""
        if cls.WB_SURFACE:
            return cls.WB_SURFACE
        return cls.__name__.removeprefix("WB").removesuffix("Client").lower()

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float,
        max_retries: int = 4,
        backoff_base_seconds: float = 2.0,
        backoff_max_seconds: float = 60.0,
        retry_after_ceiling_seconds: float = _RETRY_AFTER_CEILING_SECONDS,
        proxy: str = "",
        connect_timeout: float | None = None,
        disable_keepalive: bool = False,
        rate_gate: RateGate | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Configure the client transport and retry policy.

        Args:
            base_url: Root URL for this WB API surface.
            token: Bearer token authorising requests to this surface. Pass an
                empty string for unauthenticated surfaces (e.g. the public
                ``card.wb.ru`` storefront), which omits the header entirely — WB
                rejects a blank ``Authorization`` header with 401.
            timeout: Per-request timeout in seconds.
            max_retries: Additional attempts after the first on a retriable
                failure (429 / transient 5xx / transport error).
            backoff_base_seconds: Base for the exponential backoff sequence
                ``base * 2**(attempt - 1)``.
            backoff_max_seconds: Upper bound applied to any single backoff wait.
            retry_after_ceiling_seconds: Upper bound applied to a wait the
                SERVER demanded (``Retry-After`` / ``X-Ratelimit-Retry``), which
                is otherwise honoured past ``backoff_max_seconds``. Harvest
                clients keep the generous default — waiting out WB's stated
                window is what eventually gets the data. An INTERACTIVE caller
                passes a small value: nobody watching a spinner benefits from
                honouring a 60s demand, and failing fast lets the retry land on
                a warm cache.
            proxy: Forward proxy URL for this surface, or empty for a direct
                connection. Only the PUBLIC storefront surfaces need one — their
                anti-bot edge IP-blocks datacenter egress, so production reaches
                them from a residential IP. Holds credentials, so anything
                logged goes through :func:`scrub_credentials`.
            connect_timeout: Separate ceiling on establishing the connection,
                for surfaces reached through a proxy: a tunnel is far slower to
                open than the request is to answer, and one flat timeout has to
                be sized for the slower of the two.
            disable_keepalive: Open a NEW connection for every request. Costs a
                handshake per call and is the point when the proxy is a ROTATING
                one: its exit IP changes per tunnel, so a pooled connection pins
                every retry to the same address the server just refused.
                Measured 2026-08-17 against search.wb.ru — reusing one tunnel
                answered 1 of 4 requests, a fresh tunnel each time answered 3 of
                4, and the reused pool also produced RemoteProtocolError as the
                proxy dropped it.
            rate_gate: Pacing gate consulted before **every** attempt, retries
                included. Retrying without it is what made the 2026-07-30
                incident: the backoff ladder starts inside WB's bucket window,
                so each attempt hit the same empty bucket and paid a 30s
                stall. Defaults to no pacing for surfaces with no measured
                bucket.
        """
        self._max_retries = max_retries
        self._rate_gate: RateGate = rate_gate or NullRateGate()
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._retry_after_ceiling = retry_after_ceiling_seconds
        # NO default `Content-Type`. httpx derives it from the body it is
        # actually sending — `application/json` for `json=`, and
        # `multipart/form-data; boundary=…` for `files=` — but ONLY when the
        # header is absent, and a client-level default is never absent. A
        # default of `application/json` therefore mislabelled every multipart
        # upload, which is one endpoint: `POST /content/v3/media/file`, the only
        # write the A/Б photo rotation makes. WB answered 400 to all of them.
        # Measured live on 2026-09-05 — same client, same bytes, same token,
        # eight seconds apart: 400 with the header, 200 without it.
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = token
        if extra_headers:
            headers.update(extra_headers)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=connect_timeout or timeout),
            headers=headers,
            proxy=proxy or None,
            limits=httpx.Limits(max_keepalive_connections=0)
            if disable_keepalive
            else httpx.Limits(),
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
        headers: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        skip_rate_gate: bool = False,
    ) -> Any:
        """Perform an async request and return the decoded JSON payload.

        Args:
            method: HTTP verb (``GET`` / ``POST``).
            path: Path appended to the client's base URL.
            params: Optional query-string parameters.
            json_body: Optional JSON request body.
            files: Optional multipart payload, ``{field: (filename, bytes,
                content_type)}``. WB's media upload is the only surface that
                takes one; it goes through the same gate and retry ladder as
                every other call because its bucket is metered the same way.

        Every attempt — the first and each retry — passes the rate gate first,
        so a retry can never re-enter an empty WB bucket. WB's own
        ``x-ratelimit-remaining`` on the answer is fed back to the gate, which
        is what keeps the pacing correct when another process shares the token.

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
        # Templated once per call rather than per attempt — see `endpoint_label`
        # for why the raw path must never reach a metric label.
        endpoint = endpoint_label(path)

        for attempt in range(self._max_retries + 1):
            if not skip_rate_gate:
                try:
                    await self._rate_gate.acquire(path)
                except IntegrationError:
                    # The gate refused to send at all: WB's stated wait exceeds
                    # the queue cap. Counted, because it is a real WB failure
                    # with no HTTP status of its own — and one that is
                    # invisible in any metric derived from responses, since
                    # there is no response.
                    self._count(endpoint, "rate_blocked", None)
                    raise
            started = time.perf_counter()
            try:
                response = await self._client.request(
                    method, path, params=params, json=json_body, headers=headers, files=files
                )
                elapsed = time.perf_counter() - started
                await self._observe_rate_headers(path, response)
                # Counted BEFORE `raise_for_status`, so a 429 or a 500 is
                # recorded with its own status rather than collapsing into the
                # error branch. The status IS the interesting part of a WB
                # failure — a 429 is a budget problem and a 401 is a rotated
                # token, and they are fixed by different people.
                self._count(endpoint, str(response.status_code), elapsed)
                response.raise_for_status()
                # An empty 200 body (WB returns one for out-of-range historical
                # windows) is not valid JSON — treat it as "no data" (``None``)
                # so callers handle it like WB's explicit ``null``, instead of a
                # raw JSONDecodeError escaping the client.
                if not response.content or not response.content.strip():
                    return None
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                if status not in _RETRIABLE_STATUSES or attempt == self._max_retries:
                    logger.warning("WB API returned %s for %s %s", status, method, path)
                    raise IntegrationError(f"WildBerries API error {status} on {path}.") from exc
                # A server-demanded wait beyond the ceiling is a PENALTY BLOCK
                # (e.g. the statistics limiter answers with X-Ratelimit-Retry
                # in the thousands of seconds). Retrying inside the block only
                # extends it — measured on 2026-09-07, a request made while
                # `x-ratelimit-remaining` is 0 restarts the 15-minute window
                # rather than queueing behind it — so fail fast and let the
                # next scheduled run try.
                #
                # Against the INSTANCE's ceiling, not the module default. This
                # read the constant until 2026-09-07, which silently discarded
                # every client's override: the finance walk, whose whole reason
                # for lowering it is that it retries inside an open transaction,
                # slept off an 897 s wait and had PostgreSQL close the
                # connection under it at 300 s idle.
                demanded = _server_demanded_wait(exc.response)
                if demanded is not None and demanded > self._retry_after_ceiling:
                    # Tell the GATE before giving up, or the next caller repeats
                    # this. `_observe_rate_headers` above has only been able to
                    # clamp the bucket to empty, which reopens it one local
                    # refill later — and that refill is a constant with no
                    # knowledge of the block WB just imposed. On the statistics
                    # surface the two disagreed by minutes: a 429 demanding
                    # 1594s was followed, exactly one 900s refill later, by a
                    # second 429 demanding the remaining 694s (prod
                    # 2026-09-09). Every such early request restarts WB's
                    # window, so the hourly finance tick kept re-blocking
                    # itself. The retry branch below needs no equivalent: it
                    # already sleeps the demanded wait.
                    await self._rate_gate.penalise(path, demanded)
                    logger.warning(
                        "WB API %s on %s %s demands a %.0fs wait (penalty block); not retrying.",
                        status,
                        method,
                        path,
                        demanded,
                    )
                    raise IntegrationError(
                        f"WildBerries rate-limit block on {path} (retry in {demanded:.0f}s)."
                    ) from exc
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
                # No response, so no status: the connection failed, or WB held
                # it open until our own read timeout fired — which is exactly
                # how the analytics surface answers an over-budget request
                # (measured 2026-07-30).
                self._count(endpoint, "transport_error", time.perf_counter() - started)
                if attempt == self._max_retries:
                    # Scrubbed: a proxied surface fails with the tunnel's URL —
                    # credentials and all — inside the exception's own message.
                    logger.warning(
                        "WB API transport error for %s %s: %s",
                        method,
                        path,
                        scrub_credentials(str(exc)),
                    )
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

    def _count(self, endpoint: str, status: str, elapsed: float | None) -> None:
        """Record one WB attempt.

        Args:
            endpoint: The templated path.
            status: The HTTP status as a string, or ``transport_error`` /
                ``rate_blocked`` for the two failures that produce none.
            elapsed: Round-trip seconds, or ``None`` when nothing was sent.

        One attempt, not one call: a request that succeeds on its third try
        counts three times, two of them as failures. That is the intended
        reading — the retries are load on WB's budget and time on the harvest's
        clock whether or not the caller ever learns about them, and a metric
        that only counted final outcomes would show a healthy surface right up
        until the point retries stopped saving it.
        """
        surface = self.surface()
        WB_API_REQUESTS.labels(surface=surface, endpoint=endpoint, status=status).inc()
        if elapsed is not None:
            WB_API_DURATION.labels(surface=surface, endpoint=endpoint).observe(elapsed)

    async def _observe_rate_headers(self, path: str, response: httpx.Response) -> None:
        """Teach the gate what WB just said about this endpoint's budget.

        The analytics surface answers ``x-ratelimit-remaining`` and nothing else
        (no ``limit``, ``reset`` or ``retry`` — verified live 2026-07-30), so
        that single header is the whole feedback channel. A malformed value is
        ignored rather than guessed at.

        Args:
            path: The endpoint whose bucket this response describes.
            response: The answer WB gave, successful or not.
        """
        raw = response.headers.get("X-Ratelimit-Remaining")
        if raw is None:
            return
        try:
            remaining = int(raw.strip())
        except ValueError:
            return
        await self._rate_gate.observe(path, remaining)

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Compute the backoff delay before the next retry.

        Prefers the server's demanded wait when present (``Retry-After`` or
        WB's ``X-Ratelimit-Retry``), honouring it even beyond the exponential-
        backoff cap — retrying before the server's stated window just burns an
        attempt against the same limiter. Otherwise falls back to exponential
        backoff ``base * 2**attempt``.

        The demanded wait is capped by ``retry_after_ceiling_seconds``, which an
        interactive caller lowers to give up rather than wait out a throttle
        window (see the constructor).

        Args:
            attempt: Zero-based index of the attempt that just failed.
            response: The failed response, if any (for the wait headers).

        Returns:
            The number of seconds to wait before retrying.
        """
        if response is not None:
            demanded = _server_demanded_wait(response)
            if demanded is not None:
                return min(demanded, self._retry_after_ceiling)
        return min(self._backoff_base * (2.0**attempt), self._backoff_max)
