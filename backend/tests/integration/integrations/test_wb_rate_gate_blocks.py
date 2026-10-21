"""What WB does when it refuses, against real Redis and its real Lua.

Split from ``test_wb_rate_gate_shared_budget.py`` because it is a different
subject with a different failure. That file is about the BUDGET — how many
requests may leave, shared across processes, separate per token and per
endpoint. This one is about the BLOCK: what happens after WB has already said
no, which is governed by three numbers WB does not publish and one it does.

Every case here is a transcription of something production did.

* A block must outlast the wait WB stated. ``X-Ratelimit-Retry`` is the
  remainder of a window WB is free to extend: measured 2026-09-09, a 1594 s
  block still had 694 s left after 900 s.
* A refusal arriving with no block of ours standing must escalate. On
  2026-09-17 one workspace went 28 197 -> 18 624 -> 302 940 s in three steps,
  every one of them served for exactly as long as WB asked.
* A block earned on one token must shut the endpoint for all of them. Five
  distinct fingerprints ended that day holding expiries 0.77 s apart — one
  refusal seen five times, turned into five escalating blocks by a sequential
  fleet walk in which no seller could see the previous seller's door.

The budget stays per token through all of it, which is the other half of the
last point and the reason it is not implemented by simply sharing the bucket.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.rate_limit import TokenBucketRateGate

ENDPOINT = "/api/v5/supplier/reportDetailByPeriod"


def _gate(redis: Any, *, max_wait: float = 0.0) -> TokenBucketRateGate:
    """A settlement-shaped gate on the live test Redis, with a fast refill.

    A 200 ms refill keeps the case inside the tier's budget while exercising
    exactly the arithmetic a 960 s refill uses in production.
    """
    return TokenBucketRateGate(
        redis,
        surface="statistics-test",
        token="a-seller-token",
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=max_wait,
    )


# --------------------------------------------------------------------------- #
# A penalty block, and why WB's own number is not enough
# --------------------------------------------------------------------------- #
async def test_a_block_is_served_longer_than_wb_demanded(redis_client: Any) -> None:
    """The margin, against the real Lua rather than the fail-open fallback.

    ``X-Ratelimit-Retry`` is the remainder of a window WB is free to extend,
    not a promise about when it reopens — measured 2026-09-09, a 1594 s block
    still had 694 s left after 900 s. Serving exactly what WB says is what put
    a probe back inside an open window, and WB answers that by restarting the
    window longer.
    """
    gate = _gate(redis_client, max_wait=0.0)

    await gate.penalise(ENDPOINT, 10.0)

    shut_for = await gate.retry_after(ENDPOINT)
    assert shut_for > 10.0, "the block must outlast the wait WB stated"
    assert shut_for <= 13.0, "and not by an order of magnitude — 25% is the policy"


async def test_a_refusal_with_no_block_standing_doubles_the_last_one(
    redis_client: Any,
) -> None:
    """The escalation memory, which is the 2026-09-17 incident in one assertion.

    Three blocks in a row that day — 28 197 s, then 18 624 s, then 302 940 s.
    Each was served exactly as long as WB asked, each expired while WB's own
    window was still running, and each probe that followed was answered with a
    harder block. Nothing in our state remembered that the previous estimate
    had already been proved too short.

    So a 429 arriving when nothing of ours stands is treated as evidence about
    US, not about WB: whatever WB says this time, the block is at least twice
    what we last served.
    """
    gate = _gate(redis_client, max_wait=0.0)
    await gate.penalise(ENDPOINT, 4.0)
    # Let our own block lapse, the way a short estimate lapses in production
    # while WB is still counting.
    await asyncio.sleep(5.1)
    assert await gate.retry_after(ENDPOINT) == 0.0

    # WB refuses again and, as it did on 09-17, asks for LESS than last time.
    await gate.penalise(ENDPOINT, 1.0)

    shut_for = await gate.retry_after(ENDPOINT)
    assert shut_for > 5.0, "a repeat refusal must escalate, not shrink to what WB said"


async def test_a_standing_block_is_never_shortened(redis_client: Any) -> None:
    """A second, smaller refusal inside an open block must not reopen it early.

    WB restarting its window is the normal case here, and taking the smaller
    of the two numbers would hand the next caller a slot inside a window that
    is demonstrably still open — which is the mistake, not a recovery from it.
    """
    gate = _gate(redis_client, max_wait=0.0)
    await gate.penalise(ENDPOINT, 30.0)

    await gate.penalise(ENDPOINT, 1.0)

    assert await gate.retry_after(ENDPOINT) > 20.0


# --------------------------------------------------------------------------- #
# The budget is per token; the block is not
# --------------------------------------------------------------------------- #
def _shared_gate(redis: Any, *, token: str) -> TokenBucketRateGate:
    """A statistics-shaped gate on the live Redis, one per seller token."""
    return TokenBucketRateGate(
        redis,
        surface="statistics-test",
        token=token,
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=0.0,
        shared_block=(ENDPOINT,),
    )


async def test_one_sellers_block_shuts_the_endpoint_for_the_others(
    redis_client: Any,
) -> None:
    """The 2026-09-17 cascade, as the thing that must not happen again.

    The fleet walk is sequential and each seller carries its own bucket, so a
    refusal seller 1 earned taught seller 2 nothing: seller 2 asked a minute
    later, was refused in turn, and earned its own escalating block from the
    same shut door. Five distinct fingerprints ended that day holding
    expiries 0.77 s apart.

    The ordinary budget stays per token — see the test below, which is the
    other half and would fail if this one were implemented by simply sharing
    the bucket.
    """
    first = _shared_gate(redis_client, token="seller-one")
    second = _shared_gate(redis_client, token="seller-two")
    assert await second.retry_after(ENDPOINT) == 0.0

    await first.penalise(ENDPOINT, 30.0)

    assert await second.retry_after(ENDPOINT) > 20.0
    with pytest.raises(IntegrationError, match="rate budget"):
        await second.acquire(ENDPOINT)


async def test_an_ordinary_budget_is_still_each_sellers_own(
    redis_client: Any,
) -> None:
    """Spending seller 1's token must not spend seller 2's.

    The evidence says the metering is per token: five of them have probed
    within the same second, twenty-one times a day, for months, and a strictly
    shared one-per-917 s budget could not have survived that. Only the
    punishment looked shared, so only the punishment is.
    """
    first = _shared_gate(redis_client, token="seller-three")
    second = _shared_gate(redis_client, token="seller-four")

    await first.acquire(ENDPOINT)

    assert await second.retry_after(ENDPOINT) == 0.0
    await second.acquire(ENDPOINT)


async def test_a_gate_without_shared_blocks_is_unaffected_by_one(
    redis_client: Any,
) -> None:
    """Surfaces that did not opt in keep the old behaviour exactly.

    Analytics buckets are three deep and a refusal there means something
    milder; shutting every tenant's analytics on one 429 would be a worse
    trade than the one this buys on the settlement report.
    """
    blocked = _shared_gate(redis_client, token="seller-five")
    await blocked.penalise(ENDPOINT, 30.0)

    unshared = TokenBucketRateGate(
        redis_client,
        surface="statistics-test",
        token="seller-six",
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=0.0,
    )

    assert await unshared.retry_after(ENDPOINT) == 0.0


async def test_only_the_named_endpoint_shares_its_block(redis_client: Any) -> None:
    """The sharing is one endpoint's rule, and must not spread to its surface.

    The evidence for sharing is about `reportDetailByPeriod` and nothing else:
    several sellers holding one countdown there on 2026-09-17. Everything
    measured since says the surface at large does not behave that way — the
    ordinary bucket is not keyed on the egress address (2026-09-22, a bucket
    emptied from one address stayed empty for the same token from another),
    and `/api/v1/supplier/orders` does not escalate at all. Sharing its block
    would stall four sellers over a refusal that costs the fifth nothing.
    """
    other = "/api/v1/supplier/orders"
    earner = TokenBucketRateGate(
        redis_client,
        surface="statistics-test",
        token="seller-seven",
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=0.0,
        shared_block=(ENDPOINT,),
    )
    bystander = TokenBucketRateGate(
        redis_client,
        surface="statistics-test",
        token="seller-eight",
        capacity=1,
        refill_seconds=0.2,
        max_wait_seconds=0.0,
        shared_block=(ENDPOINT,),
    )

    await earner.penalise(other, 30.0)

    assert await bystander.retry_after(other) == 0.0, "an unshared endpoint stays private"
    assert await bystander.retry_after(ENDPOINT) == 0.0, "and shares nothing across paths"
