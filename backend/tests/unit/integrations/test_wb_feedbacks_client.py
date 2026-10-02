"""The review clients: what a page means, and which bucket the storefront spends.

Two failures here would be silent and costly. A 200 that is not the review
envelope read as an empty page would tell the walk that every review had
vanished. And the storefront is addressed per склейка — keyed on its raw path,
every ``imtId`` would get a fresh bucket and the unauthenticated reader would be
paced by nothing.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients import WBFeedbacksClient, WBStorefrontFeedbacksClient
from src.integrations.wildberries.clients.base import BaseWBClient

pytestmark = pytest.mark.unit

_SETTINGS = Settings(wb_rate_pacing_enabled=False)


class RecordingGate:
    """Records the bucket key of every acquisition; never waits."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        self.keys.append(endpoint)

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        return None

    async def penalise(self, endpoint: str, seconds: float) -> None:
        return None


def _answering(client: BaseWBClient, body: Any) -> list[httpx.Request]:
    """Point ``client`` at a transport that answers every request with ``body``."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    client._client = httpx.AsyncClient(
        base_url="https://wb.test", transport=httpx.MockTransport(handler)
    )
    return seen


def _review(review_id: str) -> dict[str, Any]:
    return {
        "id": review_id,
        "productValuation": 5,
        "createdDate": "2026-10-01T09:00:00Z",
        "productDetails": {"nmId": 953770957, "imtId": 7001},
    }


async def test_an_unreadable_item_is_counted_not_raised() -> None:
    """One odd review must not cost the page; the walk is told it is incomplete."""
    client = WBFeedbacksClient(_SETTINGS, token="a-token")
    _answering(client, {"data": {"feedbacks": [_review("a"), {"id": "b"}]}})

    page = await client.fetch_page(answered=True, take=1000, skip=0)

    assert [item.id for item in page.items] == ["a"]
    assert (page.received, page.malformed) == (2, 1)


async def test_a_body_that_is_not_the_review_list_is_an_error_not_an_empty_page() -> None:
    """An empty page ends the walk complete — and then every review is «vanished»."""
    client = WBFeedbacksClient(_SETTINGS, token="a-token")
    _answering(client, {"data": None, "error": True, "errorText": "something"})

    with pytest.raises(IntegrationError):
        await client.fetch_page(answered=False, take=1000, skip=0)


async def test_the_walk_asks_for_one_half_oldest_first() -> None:
    """``isAnswered`` is mandatory at WB, and only oldest-first gives stable offsets."""
    client = WBFeedbacksClient(_SETTINGS, token="a-token")
    seen = _answering(client, {"data": {"feedbacks": []}})

    await client.fetch_page(answered=False, take=1000, skip=950)

    assert dict(seen[0].url.params) == {
        "isAnswered": "false",
        "take": "1000",
        "skip": "950",
        "order": "dateAsc",
    }


async def test_every_storefront_read_spends_the_same_bucket() -> None:
    """Keyed on the per-склейка path, each card would get a bucket of its own."""
    gate = RecordingGate()
    client = WBStorefrontFeedbacksClient(_SETTINGS)
    client._rate_gate = gate
    _answering(client, {"valuation": "4.7", "valuationSum": 47, "feedbackCount": 10})

    await client.fetch_rating(7001)
    await client.fetch_rating(7002)

    assert gate.keys == ["/feedbacks/v2", "/feedbacks/v2"]


async def test_the_storefront_is_sent_no_credential() -> None:
    """It is public; a seller token has no business leaving for it."""
    client = WBStorefrontFeedbacksClient(_SETTINGS, token="a-seller-token")
    seen = _answering(client, {"valuation": "4.7"})

    await client.fetch_rating(7001)

    assert "authorization" not in seen[0].headers
