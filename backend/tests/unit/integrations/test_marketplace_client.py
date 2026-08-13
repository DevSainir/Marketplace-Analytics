"""Unit tests for the WB Marketplace (FBS) client's response contract.

Both shapes here were captured from live responses on 2026-08-13, and both
differ from the rest of the integration in ways that would otherwise be found
in production:

* ``/api/v3/warehouses`` answers with a **bare JSON array**, where every other
  WB surface we speak to wraps its payload in an envelope;
* ``/api/v3/stocks/{id}`` **omits** barcodes it does not know at that warehouse
  — asking about 616 returned 296 — so "absent" and ``amount: 0`` are different
  facts and the client must not invent the missing ones.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.marketplace import WBMarketplaceClient


def _client(handler: Any) -> WBMarketplaceClient:
    """Build a marketplace client whose transport is driven by ``handler``.

    Args:
        handler: A callable taking an ``httpx.Request`` and returning a response.

    Returns:
        A client wired to an in-memory mock transport (no sockets, no pacing).
    """
    settings = SimpleNamespace(
        wb_marketplace_base_url="https://marketplace.test",
        wb_http_timeout_seconds=5.0,
        wb_max_retries=0,
        wb_retry_backoff_seconds=0.0,
        wb_retry_max_backoff_seconds=0.0,
        wb_rate_pacing_enabled=False,
    )
    client = WBMarketplaceClient(settings, token="a-marketplace-token")  # type: ignore[arg-type]
    client._client = httpx.AsyncClient(
        base_url="https://marketplace.test",
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_warehouses_are_parsed_from_a_bare_array() -> None:
    """``/api/v3/warehouses`` returns a list, not an envelope."""
    client = _client(
        lambda request: httpx.Response(
            200,
            json=[
                {
                    "name": "Иван  - Москва (Внуково) НЕ УДАЛЯТЬ!!!",
                    "officeId": 236,
                    "id": 9945803,
                    "cargoType": 1,
                    "deliveryType": 1,
                }
            ],
        )
    )

    warehouses = await client.fetch_warehouses()

    assert [(w.id, w.office_id, w.delivery_type) for w in warehouses] == [(9945803, 236, 1)]


async def test_an_enveloped_warehouses_response_is_rejected() -> None:
    """A dict where WB documented an array fails loudly.

    Silently returning zero warehouses would read as "this seller runs no FBS"
    — indistinguishable from the truth, and it would quietly stop the harvest.
    """
    client = _client(lambda request: httpx.Response(200, json={"data": []}))

    with pytest.raises(IntegrationError, match="warehouses"):
        await client.fetch_warehouses()


async def test_stocks_are_parsed_with_wbs_own_size_id() -> None:
    """Each stock row carries ``chrtId``, which is what joins our size table."""
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"stocks": [{"sku": "2046161763208", "chrtId": 965033858, "amount": 480}]},
        )
    )

    stocks = await client.fetch_stocks(warehouse_id=9945803, skus=["2046161763208"])

    assert [(s.sku, s.chrt_id, s.amount) for s in stocks] == [("2046161763208", 965033858, 480)]


async def test_barcodes_wb_does_not_know_are_simply_absent() -> None:
    """WB answers only for barcodes stocked at that warehouse.

    The client must return the short list as-is rather than padding the missing
    barcodes with zeroes — "not registered here" is not "sold out".
    """
    client = _client(
        lambda request: httpx.Response(
            200, json={"stocks": [{"sku": "2046161763208", "chrtId": 965033858, "amount": 15}]}
        )
    )

    stocks = await client.fetch_stocks(
        warehouse_id=9945803, skus=["2046161763208", "2046161763215", "2046161763239"]
    )

    assert [s.sku for s in stocks] == ["2046161763208"]


async def test_an_empty_barcode_list_never_reaches_wb() -> None:
    """No barcodes means no request — the FBS budget is only ~20/min."""
    sent: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"stocks": []})

    client = _client(_record)

    stocks = await client.fetch_stocks(warehouse_id=9945803, skus=[])

    assert stocks == []
    assert sent == []
