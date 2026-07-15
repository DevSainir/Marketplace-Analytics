"""Unit tests for the card.wb.ru client's batching / resilience / validation.

The ``curl`` subprocess itself is not exercised (that needs the real binary and
network); these tests stub :meth:`WBCardClient._curl_get_json` to drive the
batch fan-out, the partial-vs-total failure policy, and the Pydantic guard.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.card import WBCardClient, _scrub


def _settings(**overrides: Any) -> SimpleNamespace:
    """A stand-in for :class:`Settings` exposing only what the client reads."""
    base = {
        "wb_card_base_url": "https://card.wb.ru",
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
    """A minimal valid ``/cards/v4/detail`` envelope for the given SKUs."""
    return {
        "data": {
            "products": [
                {"id": nm, "sizes": [{"price": {"product": (nm % 1000) * 100}}]} for nm in nm_ids
            ]
        }
    }


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
