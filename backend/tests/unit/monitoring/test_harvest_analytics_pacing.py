"""The harvest must not fire two analytics calls at once.

WB's analytics endpoints are metered per endpoint with a three-token bucket per
seller token, and an overrun is answered with HTTP 500 or a held socket rather
than a clean 429. Fanning the funnel and the stocks call out through the same
``asyncio.gather`` therefore made every contended "Refresh" burn its retries on
stalls: 145-200s per refresh, zero funnel rows persisted, and a UI that reported
a timeout on a harvest that had actually succeeded (2026-07-30).
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from src.core.exceptions import IntegrationError
from src.modules.monitoring.tasks.harvest import _fetch_analytics_in_turn

WINDOW = (date(2026, 7, 23), date(2026, 7, 29))


class FakeAnalyticsClient:
    """An analytics client that records how many calls are in flight at once.

    Each method yields to the event loop mid-call, so a caller that gathers the
    two sources would show ``max_in_flight == 2``.
    """

    def __init__(self, *, funnel_error: Exception | None = None) -> None:
        """Configure the fake, optionally failing the funnel call."""
        self._funnel_error = funnel_error
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls: list[str] = []

    async def _enter(self, label: str) -> None:
        """Register a call and let the loop run other tasks."""
        self.calls.append(label)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)

    async def fetch_sales_funnel(
        self, *, nm_ids: list[int], date_from: date, date_to: date
    ) -> list[str]:
        """Answer the daily funnel history, or raise the configured failure."""
        await self._enter("funnel")
        try:
            if self._funnel_error is not None:
                raise self._funnel_error
            return ["funnel-row"]
        finally:
            self.in_flight -= 1

    async def fetch_warehouse_stocks(self, *, nm_ids: list[int]) -> list[str]:
        """Answer the live warehouse stock snapshot."""
        await self._enter("stocks")
        try:
            return ["stock-row"]
        finally:
            self.in_flight -= 1


async def test_the_funnel_and_stocks_calls_never_overlap() -> None:
    """Only one analytics request may be in flight at a time.

    Two concurrent calls on one token are not merely impolite — they are a
    guaranteed overrun of a three-token bucket that both calls enter in the same
    millisecond, and WB punishes it by stalling rather than answering.
    """
    client = FakeAnalyticsClient()
    date_from, date_to = WINDOW

    funnel, stocks = await _fetch_analytics_in_turn(
        client,  # type: ignore[arg-type]
        nm_ids=[953770957],
        date_from=date_from,
        date_to=date_to,
    )

    assert client.max_in_flight == 1
    assert client.calls == ["funnel", "stocks"]
    assert (funnel, stocks) == (["funnel-row"], ["stock-row"])


async def test_a_failed_funnel_still_lets_the_stocks_call_run() -> None:
    """Serialising the pair must not make them share a fate.

    The harvest has always tolerated a partial WB outage; the funnel failing
    would otherwise now cost the stock snapshot too, which is the one source
    that kept working through the incident.
    """
    boom = IntegrationError("WildBerries API error 429 on /sales-funnel/products/history.")
    client = FakeAnalyticsClient(funnel_error=boom)
    date_from, date_to = WINDOW

    funnel, stocks = await _fetch_analytics_in_turn(
        client,  # type: ignore[arg-type]
        nm_ids=[953770957],
        date_from=date_from,
        date_to=date_to,
    )

    assert funnel is boom
    assert stocks == ["stock-row"]


@pytest.mark.parametrize("failing", ["funnel", "stocks"])
async def test_each_source_failure_is_returned_not_raised(failing: str) -> None:
    """Both slots carry either rows or the exception, never a raise.

    The caller distinguishes "WB withheld this" from "there was nothing to
    fetch" by inspecting these values; a raise would collapse the distinction
    and abort the surrounding harvest.
    """
    boom = IntegrationError("WildBerries API unreachable.")
    client = FakeAnalyticsClient(funnel_error=boom if failing == "funnel" else None)
    date_from, date_to = WINDOW

    funnel, stocks = await _fetch_analytics_in_turn(
        client,  # type: ignore[arg-type]
        nm_ids=[953770957],
        date_from=date_from,
        date_to=date_to,
    )

    assert not isinstance(stocks, BaseException)
    assert isinstance(funnel, BaseException) is (failing == "funnel")
