"""The WB rate gate against a live Redis: one budget, many workers.

The unit tier proves the transport consults the gate. What it cannot prove is
the part that actually broke on 2026-07-30: the budget has to be shared between
Celery's prefork WORKERS. The nightly cohort pass and an interactive «Обновить»
for the same workspace are different OS processes holding one WB token, and each
pacing itself politely still overruns WB's bucket by however many processes are
running. Only shared state fixes that, so it is tested against real Redis and
its real Lua execution.
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
