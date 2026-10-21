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
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.core.config import settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance_reports import WBFinanceReportsClient
from src.integrations.wildberries.clients.reference import WBReferenceClient
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


def _client(handler: Any) -> WBFinanceReportsClient:
    # Explicitly unpaced: these are about parsing a body, and the real gate is
    # Redis-backed — it would drain the live settlement bucket and make the
    # result depend on whether Docker happens to be up.
    client = WBFinanceReportsClient(settings, token="t", rate_gate=NullRateGate())
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
            report_id=989286628,
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
            report_id=989286628,
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
            report_id=989286628,
        ):
            pass


async def test_the_streamed_request_asks_for_wb_s_full_allowance() -> None:
    """The point of streaming is the request count, so the limit must actually
    change — a streamed call still asking for 10 000 would be all cost, no gain."""
    asked: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # The page size travels in the BODY now: the Finance methods are POST.
        asked.update(json.loads(request.content))
        return httpx.Response(200, json=[])

    client = _client(handler)
    async for _ in client.stream_report_rows(
        report_id=989286628,
    ):
        pass

    assert asked["limit"] == client.stream_limit
    assert client.stream_limit == 100_000


def _reference_client(handler: Any) -> WBReferenceClient:
    """A capture client on a fake host, unpaced — this is about decoding."""
    client = WBReferenceClient(
        settings, base_url="https://wb.test", token="t", rate_gate=NullRateGate()
    )
    client._client = httpx.AsyncClient(
        base_url="https://wb.test", transport=httpx.MockTransport(handler)
    )
    return client


async def test_a_captured_row_can_be_stored_the_way_it_arrives() -> None:
    """The defect that reached production on 2026-09-17, as an assertion.

    ijson decodes every JSON number as a `Decimal`, and `httpx`'s own `.json()`
    never did — so moving the orders feed onto the streamed reader silently
    changed the type of every price in a payload that goes straight into a JSONB
    column. `Decimal` is not JSON-serializable, and the first real body the
    capture streamed killed the whole task.

    Nothing in the unit tier could see it: the fake client the feed walks are
    tested against hands back plain dicts, so the one thing under test here —
    what the REAL reader produces — was never exercised.
    """
    body = json.dumps([{"srid": "a", "finishedPrice": 1234.56, "quantity": 3}]).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = _reference_client(handler)
    rows = [row async for batch in client.stream("/api/v1/supplier/orders") for row in batch]

    # The assertion is the storage contract, not the type: a row this client
    # returns must survive the trip into JSONB, and `json.dumps` is that trip.
    assert json.dumps(rows) == json.dumps([{"srid": "a", "finishedPrice": 1234.56, "quantity": 3}])


async def test_the_settlement_reader_keeps_its_decimals() -> None:
    """The other half of the same decision, and why it is per-caller.

    Money reaches a `Decimal` field either way; the question is what it passes
    through on the road. A binary float in the middle introduces error that was
    not in WB's answer, and this is the report every P&L figure is derived from.
    So the capture client asks for floats and this one does not — the setting
    exists because the right answer differs, not because one of them is legacy.
    """
    payload = json.dumps(_rows(1)).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    client = _client(handler)
    seen = [row async for batch in client.stream_report_rows(report_id=989286628) for row in batch]

    assert seen[0].ppvz_for_pay == Decimal("10.5")


async def test_a_stream_that_breaks_mid_body_is_an_integration_error() -> None:
    """A transport failure has to arrive as the error every caller handles.

    The retry ladder covers OPENING a stream and cannot cover this: a body half
    consumed cannot be asked for again, and the batches already yielded have
    already been committed by the caller. What has to hold is the TYPE.

    A raw `httpx.ReadError` does not hold it. It escaped the settlement walk's
    `IntegrationError` clause, killed the whole Celery task rather than the one
    page, and cost one workspace a 300 000-row window on 2026-09-24 — WB drops the
    connection on a long body often enough that this is ordinary weather.
    """

    class _BreakingStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b'[{"realizationreport_id": 900, "rrd_id": 1, "rr_dt": "2026-07-09",'
            raise httpx.ReadError("connection reset by peer")

        async def aclose(self) -> None:
            return None

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_BreakingStream())

    async def _drain() -> None:
        async with _client(_handler) as client:
            async for _batch in client.stream_report_rows(report_id=900):
                pass

    with pytest.raises(IntegrationError, match="stream broke"):
        await _drain()


async def test_a_connection_that_fails_to_open_is_an_integration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused connection before the first byte is retried, then raised as ours.

    The mid-body case above was fixed on its own; the open was left bare, so a
    `ConnectError` or a header timeout escaped every caller's `IntegrationError`
    clause and killed the Celery task the same way.
    """
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _client(handler)

    with pytest.raises(IntegrationError, match="unreachable"):
        async for _ in client.stream_report_rows(report_id=989286628):
            pass
    assert len(calls) == client._max_retries + 1


async def test_a_penalty_block_is_not_slept_off_inside_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 demanding more than the client's ceiling fails at once, without a retry.

    The finance client caps waits at 70 s because it holds the fleet lock; the
    streamed path ignored the cap and would sleep an hour on `X-Ratelimit-Retry:
    3600`, then spend another request inside WB's block.
    """
    calls: list[int] = []
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, headers={"X-Ratelimit-Retry": "3600"})

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _sleep)
    client = _client(handler)

    with pytest.raises(IntegrationError, match="block"):
        async for _ in client.stream_report_rows(report_id=989286628):
            pass
    assert (len(calls), slept) == (1, [])
