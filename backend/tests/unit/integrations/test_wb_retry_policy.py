"""Unit tests for the shared WildBerries transport retry policy.

WB is aggressively rate-limited (the advertising surface allows roughly one
request a minute), so the retry policy *is* the integration's reliability.
Every rule here was learned from a real failure mode:

* transient 5xx / 429 / transport errors are worth another attempt; a 401 is
  not — retrying a bad token just burns the budget;
* a server-named wait is honoured even past the exponential-backoff cap,
  because retrying before WB's stated window only feeds the same limiter;
* a wait in the thousands of seconds is a *penalty block*, and retrying inside
  one extends it — the run must fail fast and let the next schedule try;
* an empty 200 body (WB's answer for an out-of-range historical window) means
  "no data", not a ``JSONDecodeError`` escaping into the harvest.

``asyncio.sleep`` is patched out so the policy is tested at full speed and the
recorded delays can be asserted directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every backoff wait instead of actually sleeping.

    Returns:
        The list the policy appends its delays to, in order.
    """
    waits: list[float] = []

    async def _record(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr("src.integrations.wildberries.clients.base.asyncio.sleep", _record)
    return waits


def _client(handler: Any, *, max_retries: int = 3) -> BaseWBClient:
    """Build a client whose transport is driven by ``handler``.

    Args:
        handler: A callable taking an ``httpx.Request`` and returning a response.
        max_retries: Extra attempts allowed after the first.

    Returns:
        A client wired to an in-memory mock transport (no sockets).
    """
    client = BaseWBClient(
        base_url="https://wb.test",
        token="a-token",
        timeout=5.0,
        max_retries=max_retries,
        backoff_base_seconds=2.0,
        backoff_max_seconds=60.0,
    )
    client._client = httpx.AsyncClient(
        base_url="https://wb.test",
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_successful_response_is_returned_without_retrying(slept: list[float]) -> None:
    """A 200 short-circuits the policy entirely."""
    client = _client(lambda request: httpx.Response(200, json={"ok": True}))

    payload = await client._request("GET", "/data")

    assert payload == {"ok": True}
    assert slept == []


async def test_transient_server_error_is_retried_then_succeeds(slept: list[float]) -> None:
    """Two 503s followed by a 200 yields the payload, not an error."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"recovered": True})

    client = _client(handler)

    payload = await client._request("GET", "/data")

    assert payload == {"recovered": True}
    assert attempts["n"] == 3


async def test_backoff_grows_exponentially_between_attempts(slept: list[float]) -> None:
    """Successive retries wait base × 2**attempt — 2 s, 4 s, 8 s.

    A flat retry interval would hammer a struggling upstream at a constant rate.
    """
    client = _client(lambda request: httpx.Response(500), max_retries=3)

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert slept == [2.0, 4.0, 8.0]


async def test_backoff_is_capped(slept: list[float]) -> None:
    """No single wait exceeds the configured ceiling, however many retries run."""
    client = _client(lambda request: httpx.Response(500), max_retries=8)

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert max(slept) == 60.0


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
async def test_client_errors_fail_fast(status_code: int, slept: list[float]) -> None:
    """A 4xx is our fault, not WB's — retrying wastes the rate-limit budget."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(status_code)

    client = _client(handler)

    with pytest.raises(IntegrationError, match=str(status_code)):
        await client._request("GET", "/data")

    assert attempts["n"] == 1
    assert slept == []


async def test_retry_after_seconds_is_honoured_over_the_backoff(slept: list[float]) -> None:
    """WB naming a wait wins over our exponential schedule."""
    client = _client(
        lambda request: httpx.Response(429, headers={"Retry-After": "37"}), max_retries=1
    )

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert slept == [37.0]


async def test_retry_after_http_date_is_honoured(slept: list[float]) -> None:
    """The RFC 9110 HTTP-date form of ``Retry-After`` is parsed, not ignored."""
    target = datetime.now(UTC) + timedelta(seconds=45)
    client = _client(
        lambda request: httpx.Response(
            503, headers={"Retry-After": format_datetime(target, usegmt=True)}
        ),
        max_retries=1,
    )

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert 40.0 <= slept[0] <= 46.0


async def test_wb_ratelimit_retry_header_is_honoured(slept: list[float]) -> None:
    """The statistics surface answers with ``X-Ratelimit-Retry``, not ``Retry-After``."""
    client = _client(
        lambda request: httpx.Response(429, headers={"X-Ratelimit-Retry": "20"}), max_retries=1
    )

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert slept == [20.0]


async def test_server_wait_beyond_the_backoff_cap_is_still_honoured(slept: list[float]) -> None:
    """A 120 s demand is obeyed even though the backoff ceiling is 60 s.

    Retrying at 60 s when WB said 120 s just burns an attempt against the same
    limiter and can extend the block.
    """
    client = _client(
        lambda request: httpx.Response(429, headers={"Retry-After": "120"}), max_retries=1
    )

    with pytest.raises(IntegrationError):
        await client._request("GET", "/data")

    assert slept == [120.0]


async def test_penalty_block_fails_fast_instead_of_parking_the_task(
    slept: list[float],
) -> None:
    """A multi-hour demanded wait aborts the run rather than sleeping through it.

    WB's limiter answers a penalty block with a wait in the thousands of
    seconds. Honouring it would hold a Celery worker (and its database
    connection) hostage; the next scheduled harvest is the right retry.
    """
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(429, headers={"X-Ratelimit-Retry": "3600"})

    client = _client(handler, max_retries=4)

    with pytest.raises(IntegrationError, match="rate-limit block"):
        await client._request("GET", "/data")

    assert attempts["n"] == 1
    assert slept == []


async def test_transport_error_is_retried_then_surfaces_as_integration_error(
    slept: list[float],
) -> None:
    """A dead socket retries, then reports "unreachable" rather than leaking httpx."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler, max_retries=2)

    with pytest.raises(IntegrationError, match="unreachable"):
        await client._request("GET", "/data")

    assert len(slept) == 2


@pytest.mark.parametrize("body", [b"", b"   \n"])
async def test_empty_success_body_reads_as_no_data(body: bytes, slept: list[float]) -> None:
    """WB answers an out-of-range window with an empty 200 — that means "none".

    Letting the JSON decoder raise here would abort a whole harvest over a
    window that legitimately has no rows.
    """
    client = _client(lambda request: httpx.Response(200, content=body))

    assert await client._request("GET", "/data") is None


async def test_token_is_sent_as_the_authorization_header() -> None:
    """WB expects the raw token — a missing header is an instant 401."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={})

    client = BaseWBClient(base_url="https://wb.test", token="secret-token", timeout=5.0)
    client._client = httpx.AsyncClient(
        base_url="https://wb.test",
        transport=httpx.MockTransport(handler),
        headers=client._client.headers,
    )

    await client._request("GET", "/data")

    assert seen["authorization"] == "secret-token"


async def test_blank_token_omits_the_header_entirely() -> None:
    """The public storefront is unauthenticated; a blank header would 401.

    ``card.wb.ru`` rejects ``Authorization: `` outright, so an empty token must
    mean "send nothing", not "send an empty value".
    """
    client = BaseWBClient(base_url="https://card.wb.test", token="", timeout=5.0)

    assert "Authorization" not in client._client.headers
