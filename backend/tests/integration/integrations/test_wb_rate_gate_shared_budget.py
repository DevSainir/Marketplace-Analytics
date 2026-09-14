"""The WB rate gate against a live Redis: one budget, many workers — and a peek.

The unit tier proves the transport consults the gate. What it cannot prove is
the part that actually broke on 2026-07-30: the budget has to be shared between
Celery's prefork WORKERS. The nightly cohort pass and an interactive «Обновить»
for the same workspace are different OS processes holding one WB token, and each
pacing itself politely still overruns WB's bucket by however many processes are
running. Only shared state fixes that, so it is tested against real Redis and
its real Lua execution.

The peek (`retry_after`) is here for the same reason: it is a second Lua script
that has to agree with the first about the same bucket while writing nothing to
it. «Обновить» answers a seller out of that number instead of enqueueing a
harvest that would sit still waiting for WB, so a peek that lied — or that spent
a token — would be worse than not having one.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.rate_limit import TokenBucketRateGate

ENDPOINT = "/api/analytics/v3/sales-funnel/products/history"


def _gate(redis: Any, *, capacity: int = 3, max_wait: float = 0.5) -> TokenBucketRateGate:
    """Build a gate on the live test Redis with a fast refill.

    A 200ms refill keeps the test inside the tier's 2s budget while exercising
    exactly the arithmetic a 20s refill uses in production.
    """
    return TokenBucketRateGate(
        redis,
        surface="analytics-test",
        token="a-seller-token",
        capacity=capacity,
        refill_seconds=0.2,
        max_wait_seconds=max_wait,
    )


async def test_the_burst_is_capped_at_the_bucket_capacity(redis_client: Any) -> None:
    """Three tokens are free; the fourth request has to wait for a refill.

    WB's analytics bucket measured three deep, which is why a refresh firing two
    calls at once survives on an idle account and dies when anything else is
    spending the same budget.
    """
    gate = _gate(redis_client, capacity=3, max_wait=5.0)

    started = asyncio.get_running_loop().time()
    for _ in range(3):
        await gate.acquire(ENDPOINT)
    burst_finished = asyncio.get_running_loop().time()
    await gate.acquire(ENDPOINT)
    fourth_finished = asyncio.get_running_loop().time()

    assert burst_finished - started < 0.15
    assert fourth_finished - burst_finished >= 0.15


async def test_two_workers_share_one_budget(redis_client: Any) -> None:
    """A second gate instance sees the tokens the first one spent.

    This is the incident in miniature: two processes, one WB token. Without
    shared state both would sail through and WB would stall the second one.
    """
    worker_a = _gate(redis_client, capacity=2, max_wait=5.0)
    worker_b = _gate(redis_client, capacity=2, max_wait=5.0)

    await worker_a.acquire(ENDPOINT)
    await worker_a.acquire(ENDPOINT)
    started = asyncio.get_running_loop().time()
    await worker_b.acquire(ENDPOINT)
    waited = asyncio.get_running_loop().time() - started

    assert waited >= 0.15


async def test_a_different_token_has_its_own_budget(redis_client: Any) -> None:
    """Workspaces must not throttle each other — WB meters per seller token."""
    workspace_one = _gate(redis_client, capacity=1, max_wait=5.0)
    workspace_two = TokenBucketRateGate(
        redis_client,
        surface="analytics-test",
        token="another-seller-token",
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=5.0,
    )

    await workspace_one.acquire(ENDPOINT)
    started = asyncio.get_running_loop().time()
    await workspace_two.acquire(ENDPOINT)
    waited = asyncio.get_running_loop().time() - started

    assert waited < 0.15


async def test_a_different_endpoint_has_its_own_budget(redis_client: Any) -> None:
    """WB meters per endpoint: a drained funnel bucket must not block stocks.

    Verified live on 2026-07-30 — a funnel call answering ``remaining: 2`` sat
    beside a stocks call answering ``remaining: 0``. Sharing one bucket across
    the surface would halve a healthy harvest's throughput for no reason.
    """
    gate = _gate(redis_client, capacity=1, max_wait=5.0)

    await gate.acquire(ENDPOINT)
    started = asyncio.get_running_loop().time()
    await gate.acquire("/api/analytics/v1/stocks-report/wb-warehouses")
    waited = asyncio.get_running_loop().time() - started

    assert waited < 0.15


async def test_wbs_own_remaining_header_overrides_our_estimate(redis_client: Any) -> None:
    """``remaining: 0`` empties our bucket even when we thought it was full.

    Our capacity is a measurement, not a contract: WB can narrow the budget
    whenever it likes. Trusting the header is what keeps the client correct
    without a redeploy — and it is the only budget signal this surface sends.
    """
    gate = _gate(redis_client, capacity=3, max_wait=5.0)

    await gate.observe(ENDPOINT, 0)
    started = asyncio.get_running_loop().time()
    await gate.acquire(ENDPOINT)
    waited = asyncio.get_running_loop().time() - started

    assert waited >= 0.15


async def test_a_budget_that_will_not_refill_in_time_refuses_to_send(
    redis_client: Any,
) -> None:
    """Past the queueing cap the gate raises instead of holding the worker.

    The task retry policy can reschedule a failed harvest; it cannot reclaim a
    worker parked for an hour behind a budget that is not coming back.
    """
    gate = _gate(redis_client, capacity=1, max_wait=0.05)
    await gate.acquire(ENDPOINT)

    with pytest.raises(IntegrationError, match="rate budget"):
        await gate.acquire(ENDPOINT)


async def test_a_penalty_block_outlasts_every_refill_it_covers(redis_client: Any) -> None:
    """WB's stated wait beats our refill arithmetic, however many refills pass.

    This is the 2026-09-09 finance incident in miniature. `observe(0)` can only
    empty the bucket, which reopens one refill later; when WB's real block is
    several refills long, that reopening sends a request inside the block, and
    WB answers it by RESTARTING the window. So the hourly tick kept re-blocking
    itself: a 429 demanding 1594s, then exactly one 900s refill later a second
    demanding the remaining 694s. The block has to outrank the estimate.
    """
    gate = _gate(redis_client, capacity=3, max_wait=0.05)

    await gate.penalise(ENDPOINT, 5.0)
    await asyncio.sleep(0.5)

    with pytest.raises(IntegrationError, match="rate budget"):
        await gate.acquire(ENDPOINT)


async def test_a_lifted_block_returns_the_whole_window(redis_client: Any) -> None:
    """Once WB's wait expires the budget is whole, not trickling back.

    ``x-ratelimit-reset`` names the start of a fresh window, so the seller is
    owed the full burst at that instant. Trickling from a refill estimate would
    keep charging for a penalty WB had already lifted — and on a 15-minute
    surface that costs another harvest cycle.
    """
    gate = _gate(redis_client, capacity=3, max_wait=0.05)

    await gate.penalise(ENDPOINT, 0.3)
    await asyncio.sleep(0.4)
    started = asyncio.get_running_loop().time()
    for _ in range(3):
        await gate.acquire(ENDPOINT)
    burst = asyncio.get_running_loop().time() - started

    assert burst < 0.15


async def test_a_penalty_survives_longer_than_the_keys_ordinary_lifetime(
    redis_client: Any,
) -> None:
    """The key must outlive the block it records, or the block is forgotten.

    The standing TTL is sized for a refill; a penalty can be many times that.
    If the key expired mid-block the next caller would find no state at all,
    read it as a full bucket, and send straight into WB's window — the same
    failure the block exists to prevent, only harder to see.
    """
    gate = _gate(redis_client, capacity=3, max_wait=0.05)

    await gate.penalise(ENDPOINT, 4.0)
    ttl_ms = await redis_client.pttl(gate._key(ENDPOINT))

    assert ttl_ms > 4_000


# --- retry_after: the read-only peek -------------------------------------


async def test_an_open_bucket_peeks_as_available_now(redis_client: Any) -> None:
    """Nothing spent, nothing to wait for — «Обновить» goes straight through."""
    gate = _gate(redis_client)

    assert await gate.retry_after(ENDPOINT) == 0.0


async def test_a_peek_never_spends_a_token(redis_client: Any) -> None:
    """Looking at the page must not cost the harvest its budget.

    The page may ask this on every load and every poll. If the peek took a
    token, a seller watching the P&L would drain the bucket the settlement walk
    is metered against — turning a status line into the cause of the outage it
    reports.
    """
    gate = _gate(redis_client, capacity=1, max_wait=5.0)

    for _ in range(5):
        await gate.retry_after(ENDPOINT)

    started = asyncio.get_running_loop().time()
    await gate.acquire(ENDPOINT)

    assert asyncio.get_running_loop().time() - started < 0.15


async def test_an_emptied_bucket_peeks_as_the_wait_it_will_impose(redis_client: Any) -> None:
    """The number the seller is told to come back after is the real one.

    Same bucket, same arithmetic as `acquire`: whatever the peek reports is what
    the next request would actually have queued for.
    """
    gate = _gate(redis_client, capacity=1, max_wait=5.0)
    await gate.acquire(ENDPOINT)

    peeked = await gate.retry_after(ENDPOINT)

    assert 0 < peeked <= 0.2


async def test_a_penalty_block_outranks_the_refill_in_the_peek_too(redis_client: Any) -> None:
    """WB's own stated wait is what the seller is told, not our refill estimate.

    The two disagree badly on the settlement surface — a measured penalty ran to
    1594 s against a 900 s refill (prod 2026-09-09). Reporting the refill would
    send the seller back exactly early enough to restart WB's window.
    """
    gate = _gate(redis_client, capacity=3, max_wait=5.0)

    await gate.penalise(ENDPOINT, 30.0)
    peeked = await gate.retry_after(ENDPOINT)

    assert 29.0 <= peeked <= 30.0


async def test_one_gate_peeks_at_what_another_process_spent(redis_client: Any) -> None:
    """The whole point of a shared bucket, applied to the answer a click gives.

    The API container answers the click; the worker spends the budget. If the
    peek were per-process the page would cheerfully enqueue a harvest into a
    window the worker had already closed.
    """
    worker = _gate(redis_client, capacity=1, max_wait=5.0)
    api = _gate(redis_client, capacity=1, max_wait=5.0)

    await worker.acquire(ENDPOINT)

    assert await api.retry_after(ENDPOINT) > 0


async def test_a_reserving_caller_lets_an_urgent_one_go_first(redis_client: Any) -> None:
    """Priority, decided in the bucket rather than by agreement between callers.

    Several things want the settlement endpoint's four requests an hour: the
    hourly harvest, a seller pressing «Обновить», and the history backfill.
    Without an order they race, and the loser is whoever asked second — on
    2026-09-12 that was the fresh report, queued behind history nobody needed
    that day.

    A reserving caller declines a token that has been free for less than its
    reserve, so the urgent caller wins every contested window without knowing
    the background one exists.
    """
    urgent = _gate(redis_client, capacity=1, max_wait=5.0)
    background = _gate(redis_client, capacity=1, max_wait=0.0)

    # A fresh bucket: the token exists but has not been sitting.
    with pytest.raises(IntegrationError):
        await background.acquire("/reserve-demo", reserve_seconds=30.0)

    # ...and the urgent caller takes it without waiting at all.
    await urgent.acquire("/reserve-demo")


async def test_the_reserve_does_not_grant_extra_requests(redis_client: Any) -> None:
    """The reserve reorders callers; it must never widen the budget.

    A reserve that let a caller through early — or that refilled faster — would
    turn a courtesy into a second, contradictory limiter. After the urgent
    caller has taken the only token, a reserving caller must still be refused,
    for at least as long as anyone else would be.
    """
    urgent = _gate(redis_client, capacity=1, max_wait=0.0)
    background = _gate(redis_client, capacity=1, max_wait=0.0)

    await urgent.acquire("/reserve-budget")

    plain_wait = await urgent.retry_after("/reserve-budget")
    reserved_wait = await background.retry_after("/reserve-budget", reserve_seconds=30.0)

    assert plain_wait > 0, "the bucket handed out a second token"
    assert reserved_wait >= plain_wait, "the reserve shortened someone's wait"
