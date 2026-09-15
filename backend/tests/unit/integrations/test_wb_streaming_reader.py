"""Reading a WB response without ever holding all of it.

The settlement endpoint serves about four requests an hour per token and allows
100 000 rows in each, so the page size is the schedule rather than an efficiency
detail. What stopped us using it was our own decoding: `response.json()` makes
the caller's peak memory a function of how much the seller sold — ~12.5 KB a row,
measured live 2026-09-14, so 100 000 rows is ~1.25 GB against a 768 MiB worker.

These pin the two properties that make the big page safe: nothing accumulates,
and the rows come back whole and in order even though no chunk boundary respects
a row.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx
import pytest

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.integrations.wildberries.rate_limit import NullRateGate


def _rows(count: int, *, first_id: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "realizationreport_id": 900,
            "rrd_id": first_id + n,
            "rr_dt": "2026-07-09",
            "nm_id": 111,
            "quantity": 1,
            "ppvz_for_pay": 10.5,
        }
        for n in range(count)
    ]


def _client(handler: Any) -> WBFinanceClient:
    # Explicitly unpaced: these are about parsing a body, and the real gate is
    # Redis-backed — it would drain the live settlement bucket and make the
    # result depend on whether Docker happens to be up.
    client = WBFinanceClient(settings, token="t", rate_gate=NullRateGate())
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://wb.test"
    )
    return client


async def test_every_row_arrives_whole_and_in_order() -> None:
    """No chunk boundary lines up with a row boundary, and it must not matter.

    The body is delivered by the network in arbitrary pieces — a row is routinely
    split across two — so the parser has to be incremental rather than applied to
    whatever happens to have arrived.
    """
    payload = json.dumps(_rows(250)).encode()

    async def _chunks() -> AsyncIterator[bytes]:
        # Deliberately hostile chunking: 7 bytes, which never aligns with a row
        # boundary, a quoted string, or even a UTF-8 sequence.
        for i in range(0, len(payload), 7):
            yield payload[i : i + 7]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_chunks())

    client = _client(handler)
    seen = [
        row
        async for batch in client.stream_report_rows(
            date_from=date(2026, 7, 9),
            date_to=date(2026, 8, 8),
        )
        for row in batch
    ]

    assert len(seen) == 250
    assert [row.rrd_id for row in seen] == list(range(1, 251))


async def test_nothing_larger_than_a_batch_is_ever_held() -> None:
    """The property the whole change rests on.

    If batches grew with the response, streaming would have moved the ceiling
    without removing it — and the 100 000-row page would OOM the worker exactly
    as decoding it did.
    """
    payload = json.dumps(_rows(5_000)).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = _client(handler)
    sizes = [
        len(batch)
        async for batch in client.stream_report_rows(
            date_from=date(2026, 7, 9),
            date_to=date(2026, 8, 8),
        )
    ]

    assert sum(sizes) == 5_000
    assert max(sizes) <= client._STREAM_BATCH


async def test_a_refusal_is_raised_rather_than_returned_as_no_rows() -> None:
    """An error that reads as an empty window is how a lane declares history
    complete over a hole. It has to be loud."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    client = _client(handler)

    with pytest.raises(IntegrationError):
        async for _ in client.stream_report_rows(
            date_from=date(2026, 7, 9),
            date_to=date(2026, 8, 8),
        ):
            pass


async def test_the_streamed_request_asks_for_wb_s_full_allowance() -> None:
    """The point of streaming is the request count, so the limit must actually
    change — a streamed call still asking for 10 000 would be all cost, no gain."""
    asked: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        asked.update(dict(request.url.params))
        return httpx.Response(200, json=[])

    client = _client(handler)
    async for _ in client.stream_report_rows(
        date_from=date(2026, 7, 9),
        date_to=date(2026, 8, 8),
    ):
        pass

    assert asked["limit"] == str(client.stream_limit)
    assert client.stream_limit == 100_000
