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

from collections.abc import Mapping
from typing import Any

import httpx
import pytest

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import (
    ADVERTISING_ENDPOINT_BUCKETS,
    ANALYTICS_ENDPOINT_BUCKETS,
    STATISTICS_ENDPOINT_BUCKETS,
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
        self.penalised: list[tuple[str, float]] = []

    async def acquire(self, endpoint: str) -> None:
        """Record one pre-flight acquisition."""
        self.acquired.append(endpoint)

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        """Record one rate-header observation."""
        self.observed.append((endpoint, remaining))

    async def penalise(self, endpoint: str, seconds: float) -> None:
        """Record one penalty block handed down by WB."""
        self.penalised.append((endpoint, seconds))


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
    monkeypatch.setattr("src.integrations.wildberries.rate_limit.gates.asyncio.sleep", _record)
    monkeypatch.setattr(
        "src.integrations.wildberries.rate_limit.gates.time.monotonic", lambda: now[0]
    )
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


async def test_the_settlement_walk_gives_up_rather_than_wait_out_a_block(
    slept: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One request per ~15 minutes, and the walk must not sit in the queue.

    WB's own headers say it: `x-ratelimit-limit: 1`, `x-ratelimit-reset: 917`
    (measured 2026-09-07). A second page therefore cannot be paced into the
    same run — and waiting for it is worse than failing, because the walk pages
    inside a transaction PostgreSQL closes after 300 s idle. So the gate
    refuses instead of sleeping, and the window falls to the next tick.

    Redis is broken on purpose here. The factory reaches for the process-wide
    client, so on a developer's machine with Docker up this unit test used to
    drain the REAL statistics bucket — a bucket that then refuses for a quarter
    of an hour, failing this test and every later one that shares the key. It
    passed in CI, where nothing answers on 6379, which is the worst version of
    a broken test. The fail-open fallback paces per process with the same
    numbers, so the behaviour under test is unchanged.
    """
    monkeypatch.setattr(
        "src.integrations.wildberries.rate_limit.surfaces.get_redis", lambda: BrokenRedis()
    )
    gate = statistics_rate_gate(Settings(), token="a-statistics-token")

    await gate.acquire("/api/v5/supplier/reportDetailByPeriod")

    with pytest.raises(IntegrationError):
        await gate.acquire("/api/v5/supplier/reportDetailByPeriod")
    assert slept == []


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


async def test_a_penalty_block_is_handed_to_the_gate_and_not_only_logged(
    slept: list[float],
) -> None:
    """WB's demanded wait must reach the bucket, or the next caller repeats it.

    The gate could previously learn only `x-ratelimit-remaining`, which empties
    the bucket for exactly one local refill. On the statistics surface that
    refill is minutes shorter than the block WB actually imposes, so the next
    request went out inside the block — and each such request RESTARTS WB's
    window. Measured on prod 2026-09-09: a 429 demanding 1594s was followed one
    900s refill later by a second 429 demanding precisely the remaining 694s.
    """
    gate = FakeRateGate()
    client = _client(
        lambda _request: httpx.Response(429, headers={"X-Ratelimit-Retry": "1594"}),
        gate,
        max_retries=3,
    )

    with pytest.raises(IntegrationError, match="rate-limit block"):
        await client._request("GET", "/api/v5/supplier/reportDetailByPeriod")

    assert gate.penalised == [("/api/v5/supplier/reportDetailByPeriod", 1594.0)]


async def test_a_wait_short_enough_to_retry_does_not_penalise_the_bucket(
    slept: list[float],
) -> None:
    """Only a penalty block shuts the gate; an ordinary Retry-After is slept off.

    The retry branch already honours the demanded wait by sleeping it, so
    blocking the bucket as well would charge the caller for the same wait twice
    and turn a two-attempt recovery into a failed harvest.
    """
    gate = FakeRateGate()
    responses = [httpx.Response(429, headers={"X-Ratelimit-Retry": "2"}), httpx.Response(200)]
    client = _client(lambda _request: responses.pop(0), gate, max_retries=3)

    await client._request("GET", "/api/analytics/v3/sales-funnel/products")

    assert gate.penalised == []


async def test_a_penalised_endpoint_stays_shut_past_our_own_refill(
    slept: list[float],
) -> None:
    """A block outlasting the refill keeps refusing, rather than reopening early.

    Pins the arithmetic that produced the incident: with a 900s refill and a
    1594s block, the bucket used to hand out a token at 900s. It must not — the
    request it would allow is 694s early, and WB answers it by restarting the
    window.
    """
    gate = TokenBucketRateGate(
        BrokenRedis(),
        surface="statistics",
        token="a-statistics-token",
        capacity=1,
        refill_seconds=900.0,
        max_wait_seconds=45.0,
    )

    await gate.penalise("/api/v5/supplier/reportDetailByPeriod", 1594.0)

    with pytest.raises(IntegrationError, match="rate budget"):
        await gate.acquire("/api/v5/supplier/reportDetailByPeriod")
    assert slept == []


# --------------------------------------------------------------------------- #
# One surface is not one budget
# --------------------------------------------------------------------------- #
def _advertising_gate() -> TokenBucketRateGate:
    """The advertising gate as production builds it, on a dead Redis.

    ``BrokenRedis`` puts it on the per-process fallback, which is the same
    per-endpoint bucket lookup the Redis path makes — and it needs no server.
    """
    return TokenBucketRateGate(
        BrokenRedis(),
        surface="advertising",
        token="an-advertising-token",
        capacity=1,
        refill_seconds=20.0,
        max_wait_seconds=120.0,
        endpoint_buckets=ADVERTISING_ENDPOINT_BUCKETS,
    )


async def test_campaign_discovery_is_paced_at_wbs_rate_and_not_at_fullstats(
    slept: list[float],
) -> None:
    """The page of 2026-09-11, as arithmetic.

    ``/adv/v1/promotion/count`` is metered by WB at five a second. Paced instead
    at the surface default of one per 20 s, ten of them queue for 180 s — past
    the 120 s cap, which is a raise, a failure counter, and a pager.
    """
    gate = _advertising_gate()

    for _ in range(10):
        await gate.acquire("/adv/v1/promotion/count")

    assert sum(slept) < 2.0


async def test_fullstats_keeps_the_strict_bucket(slept: list[float]) -> None:
    """The endpoint the default is sized from must not be loosened with it.

    WB serves fullstats three times a minute. Widening the campaign-discovery
    calls is only safe while this stays where it is.
    """
    gate = _advertising_gate()

    await gate.acquire("/adv/v3/fullstats")
    await gate.acquire("/adv/v3/fullstats")

    assert slept == [pytest.approx(20.0)]


async def test_an_unlisted_advertising_endpoint_keeps_the_conservative_default(
    slept: list[float],
) -> None:
    """An endpoint WB never published a limit for is paced as the strictest one.

    ``/adv/v1/budget`` is absent from WB's table, so the lookup must miss and
    fall back rather than guess. A new endpoint arriving unpaced is the failure
    direction this whole module exists to refuse.
    """
    gate = _advertising_gate()

    await gate.acquire("/adv/v1/budget")
    await gate.acquire("/adv/v1/budget")

    assert slept == [pytest.approx(20.0)]


# --------------------------------------------------------------------------- #
# The measured table, pinned so a comment cannot drift from the code
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("surface_buckets", "endpoint", "burst", "refill"),
    [
        # Measured on «Демо» 2026-09-21 by bursting each endpoint and
        # reading WB's own `x-ratelimit-limit` / `reset` / `retry`.
        (STATISTICS_ENDPOINT_BUCKETS, "/api/v1/supplier/orders", 10, 60.0),
        (ANALYTICS_ENDPOINT_BUCKETS, "/api/analytics/v1/stocks-report/wb-warehouses", 1, 20.0),
        (ADVERTISING_ENDPOINT_BUCKETS, "/adv/v1/promotion/count", 5, 0.2),
    ],
)
def test_every_measured_endpoint_is_paced_at_the_rate_wb_published(
    surface_buckets: Mapping[str, tuple[int, float]],
    endpoint: str,
    burst: int,
    refill: float,
) -> None:
    """The table is evidence, so it belongs where it cannot rot unnoticed.

    Every one of these was wrong in the same way before 2026-09-21: the
    surface's single default stood in for endpoints WB meters separately, and
    reason it went unnoticed for so long is that an analytics overrun does not
    answer 429 — it answers HTTP 500, or holds the socket open until our own
    timeout, which reads like a WB outage rather than like our mistake.
    """
    assert surface_buckets[endpoint] == (burst, refill)


def test_the_orders_burst_is_not_mistaken_for_a_rate_again() -> None:
    """`x-ratelimit-limit: 10` is a BURST, and the refill is a minute.

    Read as «ten a minute» on 2026-09-12, which put the walk at three times
    WB's rate for nine days. Only the 429 carries the second number —
    `reset: 599, retry: 59` — and nothing in a 200 response distinguishes a
    ten-deep bucket refilling every minute from one refilling every six
    seconds.
    """
    burst, refill = STATISTICS_ENDPOINT_BUCKETS["/api/v1/supplier/orders"]

    assert burst / refill == pytest.approx(1 / 6.0), "ten tokens over ten minutes"
