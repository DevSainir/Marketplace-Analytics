"""Reading a WB response without ever holding all of it.

Separated from ``base`` because it answers a different question. The ordinary
request path asks "what did WB reply", decodes it, and hands it over; this one
asks "how do we consume a reply too large to decode", and the two have different
failure modes — notably that a retry stops being available the moment the first
byte of the body is out.

It exists because on the settlement report the page size IS the schedule. WB
serves about four requests an hour per token and allows 100 000 rows in each, so
a walk it would serve in four requests was taking thirty-three — not because of
any limit WB imposes, but because decoding a whole page made the row count a
heap problem (measured 2026-09-14: ~12.5 KB per row, 25 000 rows taking a worker
from 92 MB to 405 MB).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import ijson

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients.backoff import (
    _RETRIABLE_STATUSES,
    _server_demanded_wait,
)
from src.integrations.wildberries.endpoints import endpoint_label
from src.integrations.wildberries.rate_limit import RateGate

logger = get_logger(__name__)


class StreamingJSONMixin:
    """Streamed reads for a client that already owns a gate and a retry policy.

    A mixin rather than a helper function because it needs the client's pacing,
    metrics and connection pool — the same ones the ordinary request path uses,
    which is the point: a streamed call must not become a second way of talking
    to WB that the rate budget cannot see.
    """

    # Supplied by the client this is mixed into. Declared, not defined, so the
    # mixin can be type-checked without pretending to own them.
    _client: httpx.AsyncClient
    _rate_gate: RateGate
    _max_retries: int

    def _count(self, endpoint: str, status: str, elapsed: float | None) -> None:
        raise NotImplementedError

    async def _observe_rate_headers(self, path: str, response: httpx.Response) -> None:
        raise NotImplementedError

    async def _stream_json_items(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        batch_size: int = 2_000,
        reserve_seconds: float = 0.0,
    ) -> AsyncGenerator[list[Any], None]:
        """Stream a JSON-array response in batches, never holding all of it.

        The alternative — ``response.json()`` — decides a caller's peak memory
        by how much the seller sold. Measured on the settlement report, a row
        costs ~2.5 KB as raw JSON and ~12.5 KB once decoded and validated, so
        WB's documented ``limit`` of 100 000 is about 1.25 GB of transient heap
        against a 768 MiB worker. That is why the settlement page size was
        pinned at 10 000, and why a walk that WB would happily serve in four
        requests was taking thirty-three.

        Here the body is consumed as it arrives and parsed incrementally, so the
        peak is ``batch_size`` rather than the page. The page size becomes a
        throughput knob again — which is what it should always have been, since
        on this endpoint requests are the scarce resource and bytes are not.

        **Retries stop once the first byte of the body is out.** The ladder
        below protects establishing the response: a refused gate, a connection
        error, a 429, a 5xx. After that a retry would have to either replay
        batches the caller has already committed or silently skip them, and
        neither is a thing this can decide for the caller. A mid-stream failure
        raises, and the caller re-asks for the same page on its next tick — the
        settlement walk already resumes from an ``rrdid`` cursor for exactly
        this reason.

        Args:
            method: HTTP verb.
            path: Path appended to the client's base URL.
            params: Optional query-string parameters.
            batch_size: Rows to accumulate before handing a batch over. The
                memory ceiling, in rows.
            reserve_seconds: Passed to the rate gate — non-zero marks this as
                background work that yields its window to anything urgent.

        Yields:
            Lists of decoded rows, in WB's order, at most ``batch_size`` long.

        Raises:
            IntegrationError: On a refused gate, an exhausted retry ladder, or a
                failure part-way through the body.
        """
        endpoint = endpoint_label(path)
        response = await self._open_stream(
            method, path, params=params, endpoint=endpoint, reserve_seconds=reserve_seconds
        )
        if response is None:
            return
        buffer = ijson.sendable_list()
        coro = ijson.items_coro(buffer, "item")
        try:
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                coro.send(chunk)
                # Drain in slices rather than testing once: a single chunk can
                # carry many batches' worth of rows — the transport decides how
                # the body is cut up, and a test or a fast localhost will hand
                # over the whole thing at once. Checking only once let the
                # buffer grow to the size of the chunk, which is the ceiling
                # this method exists to remove.
                while len(buffer) >= batch_size:
                    batch = buffer[:batch_size]
                    del buffer[:batch_size]
                    yield batch
            coro.close()
            if buffer:
                yield list(buffer)
        except ijson.JSONError as exc:
            raise IntegrationError(f"Malformed JSON from {path}: {exc}") from exc
        finally:
            await response.aclose()

    async def _open_stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        endpoint: str,
        reserve_seconds: float,
    ) -> httpx.Response | None:
        """Get a streamed response past the gate and the retry ladder.

        Split from the reading so the ladder keeps one shape for both kinds of
        call. It ends the moment the body starts: everything retriable — a
        refused gate, a transport error, a 429, a 5xx — is decided from the
        status line, which arrives before any byte the caller will see.

        Returns:
            An open streamed response, or ``None`` when WB answered with no body
            at all, which is how it says a historical window is empty.
        """
        last_exc: httpx.HTTPError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                await self._rate_gate.acquire(path, reserve_seconds=reserve_seconds)
            except IntegrationError:
                self._count(endpoint, "rate_blocked", None)
                raise
            started = time.perf_counter()
            request = self._client.build_request(method, path, params=params)
            response = await self._client.send(request, stream=True)
            try:
                elapsed = time.perf_counter() - started
                await self._observe_rate_headers(path, response)
                self._count(endpoint, str(response.status_code), elapsed)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # The body of an error IS the message and is small. Reading it
                # here also frees the connection before any backoff sleep.
                await exc.response.aread()
                await response.aclose()
                last_exc = exc
                status = exc.response.status_code
                if status not in _RETRIABLE_STATUSES or attempt == self._max_retries:
                    logger.warning("WB API returned %s for %s %s", status, method, path)
                    raise IntegrationError(f"WildBerries API error {status} on {path}.") from exc
                demanded = _server_demanded_wait(exc.response)
                if status == 429 and demanded is not None:
                    await self._rate_gate.penalise(path, demanded)
                await asyncio.sleep(demanded if demanded is not None else 2**attempt)
                continue
            except Exception:
                await response.aclose()
                raise
            return response
        raise IntegrationError(f"WildBerries API unreachable on {path}.") from last_exc
