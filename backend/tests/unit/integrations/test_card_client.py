"""Unit tests for the storefront card client: request shape, batching,
resilience and validation.

The ``curl`` subprocess itself is not exercised (that needs the real binary and
network); these tests stub :meth:`WBCardClient._curl_get_json` to drive the
batch fan-out, the partial-vs-total failure policy, and the Pydantic guard.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.card import WBCardClient, _scrub


def _settings(**overrides: Any) -> SimpleNamespace:
    """A stand-in for :class:`Settings` exposing only what the client reads."""
    base = {
        "wb_card_base_url": "https://www.wildberries.ru",
        "wb_card_path": "/__internal/u-card/cards/v4/detail",
        "wb_card_device_id": "site_test0000000000000000000000000",
        "wb_card_dest": -1255563,
        "wb_card_spp": 30,
        "wb_card_proxy": "",
        "wb_http_timeout_seconds": 30.0,
        "wb_card_connect_timeout_seconds": 15.0,
        "wb_card_max_retries": 3,
        "wb_retry_backoff_seconds": 0.0,
        "wb_retry_max_backoff_seconds": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _envelope(nm_ids: list[int]) -> dict[str, Any]:
    """The storefront's current envelope: ``products`` at the top level.

    Measured 2026-09-22 — the move off ``card.wb.ru`` dropped the ``data``
    wrapper. The legacy shape is covered by :func:`_legacy_envelope`.
    """
    return {
        "products": [
            {"id": nm, "sizes": [{"price": {"product": (nm % 1000) * 100}}]} for nm in nm_ids
        ]
    }


def _legacy_envelope(nm_ids: list[int]) -> dict[str, Any]:
    """The pre-2026-09-22 envelope, with ``products`` nested under ``data``."""
    return {"data": _envelope(nm_ids)}


async def test_batches_split_and_merge() -> None:
    """SKUs beyond one batch are fanned out and the results merged in full."""
    client = WBCardClient(_settings())
    client._DETAIL_BATCH = 2  # type: ignore[misc]  # force multiple batches
    seen_urls: list[str] = []

    async def fake(url: str) -> Any:
        seen_urls.append(url)
        nms = [int(x) for x in url.split("nm=")[1].split(";")]
        return _envelope(nms)

    client._curl_get_json = fake  # type: ignore[method-assign]

    products = await client.fetch_customer_prices([111, 222, 333, 444, 555])

    assert len(seen_urls) == 3  # 2 + 2 + 1
    assert sorted(p.nm_id for p in products) == [111, 222, 333, 444, 555]


async def test_partial_failure_keeps_successful_batches() -> None:
    """One dead batch is dropped; the rest still yield their products."""
    client = WBCardClient(_settings())
    client._DETAIL_BATCH = 2  # type: ignore[misc]

    async def fake(url: str) -> Any:
        nms = [int(x) for x in url.split("nm=")[1].split(";")]
        if 333 in nms:  # the second batch fails outright
            raise IntegrationError("card.wb.ru request failed: HTTP 403.")
        return _envelope(nms)

    client._curl_get_json = fake  # type: ignore[method-assign]

    products = await client.fetch_customer_prices([111, 222, 333, 444, 555])

    # First and third batches survive; the 333/444 batch is dropped.
    assert sorted(p.nm_id for p in products) == [111, 222, 555]


async def test_total_failure_raises() -> None:
    """When EVERY batch fails, the error surfaces (harvest skips the source)."""
    client = WBCardClient(_settings())
    client._DETAIL_BATCH = 2  # type: ignore[misc]

    async def fake(url: str) -> Any:
        raise IntegrationError("card.wb.ru request failed: HTTP 403.")

    client._curl_get_json = fake  # type: ignore[method-assign]

    with pytest.raises(IntegrationError, match=r"all .* batch"):
        await client.fetch_customer_prices([111, 222, 333])


async def test_bad_shape_raises() -> None:
    """A response without a products list is rejected (not silently empty)."""
    client = WBCardClient(_settings())

    async def fake(url: str) -> Any:
        return {"data": {"unexpected": True}}

    client._curl_get_json = fake  # type: ignore[method-assign]

    with pytest.raises(IntegrationError, match="products list"):
        await client.fetch_customer_prices([111])


async def test_pydantic_validation_surfaces_api_change() -> None:
    """A malformed product row fails validation instead of corrupting data."""
    client = WBCardClient(_settings())

    async def fake(url: str) -> Any:
        # ``id`` gone / renamed — a shape change Pydantic must catch.
        return {"data": {"products": [{"identifier": 111, "sizes": []}]}}

    client._curl_get_json = fake  # type: ignore[method-assign]

    with pytest.raises(IntegrationError, match="validation"):
        await client.fetch_customer_prices([111])


async def test_empty_input_is_a_noop() -> None:
    """No SKUs → no request, empty result."""
    client = WBCardClient(_settings())
    called = False

    async def fake(url: str) -> Any:
        nonlocal called
        called = True
        return _envelope([])

    client._curl_get_json = fake  # type: ignore[method-assign]

    assert await client.fetch_customer_prices([]) == []
    assert called is False


def test_scrub_redacts_proxy_credentials() -> None:
    """Credentials never reach the logs."""
    dirty = "curl: (7) Failed to connect via http://user:secretpass@1.2.3.4:443"

    assert "secretpass" not in _scrub(dirty)
    assert "//***@1.2.3.4:443" in _scrub(dirty)


async def test_no_more_than_two_batches_are_in_flight_at_once() -> None:
    """The proxy will not open more than a couple of tunnels at a time.

    Measured from the worker on 2026-09-07: sequential and 2-concurrent
    requests all answered 200 in about a second; at 4 one batch of four never
    got a tunnel at all and died on the connect timeout, and at 8 two did. The
    cost is invisible downstream — a dropped batch leaves those SKUs without a
    customer price, which reads exactly like a SKU WB has no price for — so the
    ceiling is pinned here rather than left to a comment.
    """
    client = WBCardClient(_settings())
    client._DETAIL_BATCH = 1  # type: ignore[misc]  # one batch per SKU
    in_flight = 0
    peak = 0

    async def fake(url: str) -> Any:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)  # yield, so overlapping calls actually overlap
        in_flight -= 1
        return _envelope([int(url.split("nm=")[1])])

    client._curl_get_json = fake  # type: ignore[method-assign]

    products = await client.fetch_customer_prices([1, 2, 3, 4, 5, 6, 7, 8])

    assert len(products) == 8
    assert peak <= 2


async def test_request_targets_the_storefront_path_with_the_device_header() -> None:
    """The URL is the configured storefront path and ``deviceid`` is sent.

    Both are what the move off ``card.wb.ru`` turned load-bearing (2026-09-22):
    the path because WB retires storefront versions without notice, and the
    header because it alone is what turns 403 into 200.
    """
    client = WBCardClient(_settings())
    captured: dict[str, Any] = {}

    async def fake_exec(*args: str, **kwargs: Any) -> Any:
        captured["args"] = args
        raise OSError("not run")

    import src.integrations.wildberries.clients.card as card_module

    original = asyncio.create_subprocess_exec
    card_module.asyncio.create_subprocess_exec = fake_exec  # type: ignore[assignment]
    try:
        with pytest.raises(IntegrationError):
            await client.fetch_customer_prices([123])
    finally:
        card_module.asyncio.create_subprocess_exec = original  # type: ignore[assignment]

    args = captured["args"]
    url = args[-1]
    assert url.startswith("https://www.wildberries.ru/__internal/u-card/cards/v4/detail?")
    assert url.endswith("&nm=123")
    assert "dest=-1255563" in url
    assert "deviceid: site_test0000000000000000000000000" in args


async def test_legacy_data_wrapped_envelope_is_still_accepted() -> None:
    """The pre-move ``{"data": {"products": ...}}`` shape still parses.

    WB moved the wrapper once; nothing says it will not move back, and reading
    both costs one branch.
    """
    client = WBCardClient(_settings())

    async def fake(url: str) -> Any:
        return _legacy_envelope([777])

    client._curl_get_json = fake  # type: ignore[method-assign]

    products = await client.fetch_customer_prices([777])

    assert [p.nm_id for p in products] == [777]
