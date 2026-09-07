"""Unit tests for the client-side pacing of WB's per-endpoint token buckets.

Every rule here was learned from the 2026-07-30 incident, when «Обновить»
appeared never to work. The mechanism, measured live that morning:

* the analytics surface meters per endpoint, three tokens deep per seller token,
  and publishes what is left in ``x-ratelimit-remaining``;
* overrunning it does NOT reliably answer 429 — WB returned HTTP 500, and then
  held the socket open until our own 30s read timeout fired;
* our retry ladder starts at 2s, well inside that bucket's window, so all four
  retries landed in the same empty bucket. A two-second refresh became a
  three-minute one that persisted zero funnel rows.

So the gate must be consulted before EVERY attempt, retries included, and WB's
own header is the feedback that keeps it honest.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import (
    NullRateGate,
    TokenBucketRateGate,
    analytics_rate_gate,
    statistics_rate_gate,
)


class FakeRateGate:
    """Records what the transport asked of the gate, and never waits."""

    def __init__(self) -> None:
        """Start with empty call logs."""
        self.acquired: list[str] = []
        self.observed: list[tuple[str, int | None]] = []

    async def acquire(self, endpoint: str) -> None:
        """Record one pre-flight acquisition."""
        self.acquired.append(endpoint)

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Record one rate-header observation."""
        self.observed.append((endpoint, remaining))


class BrokenRedis:
    """An async Redis stand-in whose every call fails, to pin the fail-open path."""

    async def eval(self, *args: Any, **kwargs: Any) -> Any:
        """Fail the way an unreachable Redis does."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        raise RedisConnectionError("redis is down")


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every wait instead of sleeping, in both modules under test.

    A recorded wait also advances the gate's clock, so a paced loop makes
    progress at full speed instead of spinning against a frozen
    ``time.monotonic``.
    """
    waits: list[float] = []
    now = [1000.0]

    async def _record(delay: float) -> None:
        waits.append(delay)
        now[0] += delay

    monkeypatch.setattr("src.integrations.wildberries.clients.base.asyncio.sleep", _record)
    monkeypatch.setattr("src.integrations.wildberries.rate_limit.asyncio.sleep", _record)
    monkeypatch.setattr("src.integrations.wildberries.rate_limit.time.monotonic", lambda: now[0])
    return waits


def _client(handler: Any, gate: Any, *, max_retries: int = 3) -> BaseWBClient:
    """Build a client with a mock transport and the given gate."""
    client = BaseWBClient(
        base_url="https://wb.test",
        token="a-token",
        timeout=5.0,
        max_retries=max_retries,
        backoff_base_seconds=2.0,
        backoff_max_seconds=60.0,
        rate_gate=gate,
    )
    client._client = httpx.AsyncClient(
        base_url="https://wb.test",
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_every_retry_passes_the_gate_again(slept: list[float]) -> None:
    """A retry must re-acquire a rate token, not just wait out the backoff.

    This is the incident's core defect. The backoff ladder (2s, 4s, ...) starts
    inside WB's 20s bucket window, so a retry that skips the gate re-enters an
    empty bucket and buys another 30s stall instead of an answer.
    """
    gate = FakeRateGate()
    answers = [httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"ok": True})]
    client = _client(lambda request: answers.pop(0), gate)

    payload = await client._request("GET", "/api/analytics/v3/sales-funnel/products/history")

    assert payload == {"ok": True}
    assert gate.acquired == ["/api/analytics/v3/sales-funnel/products/history"] * 3


async def test_wb_remaining_header_is_fed_back_to_the_gate() -> None:
    """``x-ratelimit-remaining`` is the only budget signal this surface sends.

    WB sends no ``limit``, ``reset`` or ``retry`` header on seller-analytics
    (verified live), so ignoring ``remaining`` leaves the client guessing at a
    budget WB is willing to state outright.
    """
    gate = FakeRateGate()
    client = _client(
        lambda request: httpx.Response(200, json=[], headers={"X-Ratelimit-Remaining": "2"}),
        gate,
    )

    await client._request("POST", "/api/analytics/v1/stocks-report/wb-warehouses")

    assert gate.observed == [("/api/analytics/v1/stocks-report/wb-warehouses", 2)]


async def test_an_exhausted_bucket_is_observed_even_though_the_request_failed(
    slept: list[float],
) -> None:
    """The 500 that means "bucket empty" must still teach the gate.

    WB answers an overrun with a 500 carrying ``remaining: 0``. Learning only
    from successful responses would drop exactly the signal that matters.
    """
    gate = FakeRateGate()
    answers = [
        httpx.Response(500, headers={"X-Ratelimit-Remaining": "0"}),
        httpx.Response(200, json={"ok": True}, headers={"X-Ratelimit-Remaining": "2"}),
    ]
    client = _client(lambda request: answers.pop(0), gate)

    await client._request("POST", "/api/analytics/v3/sales-funnel/products")

    assert gate.observed == [
        ("/api/analytics/v3/sales-funnel/products", 0),
        ("/api/analytics/v3/sales-funnel/products", 2),
    ]


async def test_a_missing_or_malformed_rate_header_teaches_the_gate_nothing() -> None:
    """No header means no information — not a guessed zero.

    Surfaces other than analytics send nothing; a guess there would throttle a
    perfectly healthy endpoint.
    """
    gate = FakeRateGate()
    client = _client(
        lambda request: httpx.Response(200, json={}, headers={"X-Ratelimit-Remaining": "n/a"}),
        gate,
    )

    await client._request("GET", "/adv/v1/promotion/count")

    assert gate.observed == []


async def test_the_gate_can_refuse_to_send_rather_than_queue_forever(
    slept: list[float],
) -> None:
    """A request that would queue past the cap fails instead of parking a worker.

    A harvest the retry policy can reschedule in two minutes is strictly better
    than a Celery worker held hostage by a budget that is not refilling.
    """
    gate = TokenBucketRateGate(
        BrokenRedis(),
        surface="analytics",
        token="a-token",
        capacity=1,
        refill_seconds=20.0,
        max_wait_seconds=5.0,
    )
    await gate.acquire("/api/analytics/v3/sales-funnel/products")

    with pytest.raises(IntegrationError, match="rate budget"):
        await gate.acquire("/api/analytics/v3/sales-funnel/products")


async def test_pacing_survives_a_redis_outage_by_spacing_per_process(
    slept: list[float],
) -> None:
    """Redis down degrades pacing; it does not stop the harvest.

    Per-process spacing is weaker than the shared bucket (each worker paces only
    itself), but it is what keeps a nightly harvest running through a cache
    outage — and it still refuses to fire two analytics calls back to back.
    """
    gate = TokenBucketRateGate(
        BrokenRedis(),
        surface="analytics",
        token="a-token",
        capacity=3,
        refill_seconds=20.0,
        max_wait_seconds=60.0,
    )

    await gate.acquire("/api/analytics/v3/sales-funnel/products/history")
    await gate.acquire("/api/analytics/v3/sales-funnel/products/history")

    assert len(slept) == 1
    assert slept[0] == pytest.approx(20.0, abs=0.5)


def test_pacing_can_be_switched_off_without_touching_call_sites() -> None:
    """With pacing disabled the analytics client gets a gate that never waits.

    Unit and component tiers must not need a Redis to construct a WB client.
    """
    gate = analytics_rate_gate(Settings(wb_rate_pacing_enabled=False), token="a-token")

    assert isinstance(gate, NullRateGate)


async def test_the_settlement_walk_will_not_send_two_pages_within_a_minute(
    slept: list[float],
) -> None:
    """The gate that exists because a second page cost a fifteen-minute block.

    `reportDetailByPeriod` served the freshness probe and the walk's first page
    back to back on 2026-09-07, then answered the second page — 26 s later —
    with a 429 demanding 934 s. No backoff ladder can wait that out from inside
    the harvest's open transaction, so the second request must not be sent
    until a token exists.
    """
    gate = statistics_rate_gate(Settings(), token="a-statistics-token")

    await gate.acquire("/api/v5/supplier/reportDetailByPeriod")
    await gate.acquire("/api/v5/supplier/reportDetailByPeriod")

    assert len(slept) == 1
    assert slept[0] >= 60.0


def test_a_finance_client_is_paced_unless_pacing_is_switched_off() -> None:
    """The wiring, not the gate: a client built without one pages unguarded.

    Asserted here because nothing else would notice — an unpaced walk works
    perfectly for every seller small enough to fit one page, which is how this
    reached production in the first place.
    """
    from src.integrations.wildberries.clients.finance import WBFinanceClient

    paced = WBFinanceClient(Settings(), token="a-statistics-token")
    unpaced = WBFinanceClient(Settings(wb_rate_pacing_enabled=False), token="a-statistics-token")

    assert isinstance(paced._rate_gate, TokenBucketRateGate)
    assert isinstance(unpaced._rate_gate, NullRateGate)
