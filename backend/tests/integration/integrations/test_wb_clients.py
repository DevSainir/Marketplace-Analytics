"""Integration tests for the WildBerries clients against a mock HTTP transport.

"Integration" here means the whole client is exercised end to end — request
construction, pagination, envelope unwrapping, and Pydantic validation — with
only the network replaced. The canned envelopes in ``tests/support/wb_payloads``
are copied from observed WB responses rather than written from any document, so
a drafting error in the ``wildberries-api`` skill cannot propagate into them.

Real WB calls are deliberately out of scope: they need live seller tokens, they
are rate-limited to roughly one request a minute, and they would make the suite
depend on a third party's uptime.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.prices import WBPricesClient
from src.integrations.wildberries.clients.statistics import WBStatisticsClient
from tests.support.wb_payloads import goods_filter_page, price_good, sale_record


def _mock(client: Any, handler: Any) -> Any:
    """Swap a live client's transport for an in-memory handler.

    Args:
        client: The WB client to rewire.
        handler: A callable taking an ``httpx.Request``.

    Returns:
        The same client, now talking to the mock transport.
    """
    client._client = httpx.AsyncClient(
        base_url=str(client._client.base_url),
        transport=httpx.MockTransport(handler),
        headers=client._client.headers,
    )
    return client


# --------------------------------------------------------------------------- #
# Prices & Discounts
# --------------------------------------------------------------------------- #
async def test_prices_client_parses_the_seller_price() -> None:
    """``discountedPrice`` is the seller price the whole matrix is priced from."""
    client = _mock(
        WBPricesClient(settings, token="t"),
        lambda request: httpx.Response(
            200, json=goods_filter_page(goods=[price_good(nm_id=1, discounted_price=1490.0)])
        ),
    )

    goods = await client.fetch_prices()

    assert len(goods) == 1
    assert goods[0].nm_id == 1
    await client.aclose()


async def test_prices_client_sends_the_token_and_paging_parameters() -> None:
    """The request WB receives carries the auth header and an explicit page."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=goods_filter_page(goods=[]))

    client = _mock(WBPricesClient(settings, token="prices-token"), handler)

    await client.fetch_prices()

    assert seen["auth"] == "prices-token"
    assert "limit=1000" in seen["url"]
    assert "offset=0" in seen["url"]
    await client.aclose()


async def test_prices_client_walks_every_page() -> None:
    """A full page means "there is more"; a short page ends the walk.

    Stopping after the first page would silently price the account from its
    first thousand SKUs only.
    """
    pages: list[list[dict[str, Any]]] = [
        [price_good(nm_id=i) for i in range(1000)],
        [price_good(nm_id=10_000)],
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[calls["n"]] if calls["n"] < len(pages) else []
        calls["n"] += 1
        return httpx.Response(200, json=goods_filter_page(goods=page))

    client = _mock(WBPricesClient(settings, token="t"), handler)

    goods = await client.fetch_prices()

    assert len(goods) == 1001
    assert calls["n"] == 2
    await client.aclose()


async def test_prices_client_rejects_a_malformed_envelope() -> None:
    """A 200 with the wrong shape must raise, not read as "no prices".

    Defaulting to an empty list would write a zero-price snapshot over real
    prices, and every derived revenue figure would silently collapse to zero.
    """
    client = _mock(
        WBPricesClient(settings, token="t"),
        lambda request: httpx.Response(200, json={"data": {"unexpected": []}}),
    )

    with pytest.raises(IntegrationError, match="listGoods"):
        await client.fetch_prices()

    await client.aclose()


# --------------------------------------------------------------------------- #
# Statistics (sale-date buyouts)
# --------------------------------------------------------------------------- #
async def test_statistics_client_returns_one_record_per_operation() -> None:
    """Sales and returns both arrive as rows keyed by their operation id."""
    client = _mock(
        WBStatisticsClient(settings, token="t"),
        lambda request: httpx.Response(
            200,
            json=[
                sale_record(srid="a", sale_date="2026-07-01T10:00:00"),
                sale_record(srid="b", sale_date="2026-07-01T11:00:00", is_return=True),
            ],
        ),
    )

    records = await client.fetch_sales(changed_since=datetime(2026, 7, 1, tzinfo=UTC))

    assert len(records) == 2
    await client.aclose()


async def test_statistics_client_filters_on_last_change_date() -> None:
    """``dateFrom`` filters by ``lastChangeDate``, which is what makes the nightly
    increment pick up a return processed today for a months-old sale."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[])

    client = _mock(WBStatisticsClient(settings, token="t"), handler)

    await client.fetch_sales(changed_since=datetime(2026, 7, 1, 12, 0, tzinfo=UTC))

    assert "dateFrom=2026-07-01T12" in seen["url"]
    assert "flag=0" in seen["url"]
    await client.aclose()


async def test_statistics_client_rejects_a_non_list_payload() -> None:
    """This endpoint returns a bare array; anything else is a contract break."""
    client = _mock(
        WBStatisticsClient(settings, token="t"),
        lambda request: httpx.Response(200, json={"data": []}),
    )

    with pytest.raises(IntegrationError, match="expected a list"):
        await client.fetch_sales(changed_since=datetime(2026, 7, 1, tzinfo=UTC))

    await client.aclose()


async def test_statistics_client_uses_a_slower_backoff_than_the_shared_default() -> None:
    """This surface allows ~1 request/minute and its 429s carry no ``Retry-After``.

    With the shared 2/4/8/16 s ladder every retry would land inside the same
    limiter window and the whole budget would burn in 30 seconds.
    """
    client = WBStatisticsClient(settings, token="t")

    assert client._backoff_base >= 20.0
    assert client._backoff_max >= 120.0

    await client.aclose()


async def test_an_empty_body_reads_as_no_rows_not_a_crash() -> None:
    """WB answers an out-of-range window with an empty 200.

    A JSON decode error here would abort the whole harvest over a window that
    legitimately has no data.
    """
    client = _mock(
        WBStatisticsClient(settings, token="t"),
        lambda request: httpx.Response(200, content=b""),
    )

    with pytest.raises(IntegrationError, match="expected a list"):
        await client.fetch_sales(changed_since=datetime(2026, 7, 1, tzinfo=UTC))

    await client.aclose()


async def test_the_client_closes_its_connection_pool() -> None:
    """The clients are async context managers; leaking pools exhausts sockets.

    The nightly harvest builds one client per surface per workspace — a leaked
    pool per run adds up fast in a long-lived worker.
    """
    async with WBPricesClient(settings, token="t") as client:
        assert client._client.is_closed is False

    assert client._client.is_closed is True
