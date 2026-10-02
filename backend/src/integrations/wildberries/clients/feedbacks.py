"""Reviews: the seller feedbacks API, and the public storefront's rating summary.

What each source can and cannot say is in
:mod:`src.integrations.wildberries.schemas.feedbacks`. This module only fetches
them: one page of reviews at a time, and one склейка's summary at a time. Both
are deliberately one call per method so the caller decides the pace and the
memory — a large кабинет holds ~150k reviews, which must never be in memory at
once on a 768 MiB worker.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import (
    feedbacks_rate_gate,
    storefront_feedbacks_rate_gate,
)
from src.integrations.wildberries.schemas.feedbacks import WBFeedback, WBStorefrontRating

logger = get_logger(__name__)

#: The seller API's review list. ``take`` is capped by WB at 5000.
FEEDBACKS_PATH = "/api/v1/feedbacks"

#: The storefront summary is addressed per склейка; every request is paced on
#: this one key instead (see :func:`storefront_feedbacks_rate_gate`).
STOREFRONT_RATE_KEY = "/feedbacks/v2"


@dataclass(frozen=True, slots=True)
class FeedbackPage:
    """One page of the review list.

    Attributes:
        items: The reviews that parsed.
        received: How many items WB sent, parsed or not — what decides whether
            the page was full and the walk must go on.
        malformed: Items dropped because they did not parse. Any at all makes
            the walk incomplete: a review we could not read is not a review
            that vanished.
    """

    items: list[WBFeedback]
    received: int
    malformed: int


class WBFeedbacksClient(BaseWBClient):
    """The seller's review list, «Вопросы и отзывы» scope."""

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the client.

        Args:
            settings: Transport configuration and the feedbacks host.
            token: The workspace's «Вопросы и отзывы» (or unified) token.
        """
        super().__init__(
            base_url=settings.wb_feedbacks_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            rate_gate=feedbacks_rate_gate(settings, token=token),
        )

    async def fetch_page(self, *, answered: bool, take: int, skip: int) -> FeedbackPage:
        """Fetch one page of reviews, oldest first.

        WB splits the list in two by ``isAnswered`` and serves neither half
        without the flag, so a complete walk reads both. Oldest first because an
        offset is only a stable resume point when new reviews land at the end.

        Args:
            answered: Which half of the list.
            take: Page size, at most 5000.
            skip: Offset into that half.

        Returns:
            The page, with what could not be parsed counted rather than raised.

        Raises:
            IntegrationError: On a transport failure, or a 200 whose body is not
                the review envelope — that must never read as an empty page, or
                the caller would conclude every review had vanished.
        """
        payload = await self._request(
            "GET",
            FEEDBACKS_PATH,
            params={
                "isAnswered": "true" if answered else "false",
                "take": take,
                "skip": skip,
                "order": "dateAsc",
            },
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        raw = data.get("feedbacks") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise IntegrationError("Unexpected feedbacks response shape (expected data.feedbacks).")
        items: list[WBFeedback] = []
        malformed = 0
        for entry in raw:
            try:
                items.append(WBFeedback.model_validate(entry))
            except ValidationError:
                malformed += 1
        if malformed:
            logger.warning(
                "feedbacks: %d of %d items on a page did not parse.", malformed, len(raw)
            )
        return FeedbackPage(items=items, received=len(raw), malformed=malformed)


class WBStorefrontFeedbacksClient(BaseWBClient):
    """The public storefront's rating summary for one склейка. No token."""

    WB_SURFACE = "storefront_feedbacks"

    def __init__(self, settings: Settings, *, token: str = "") -> None:
        """Build the client.

        Args:
            settings: Transport configuration and the storefront host.
            token: Ignored and never sent — the storefront is unauthenticated.
                Accepted so every client builds from ``(settings, token=...)``.
        """
        del token
        super().__init__(
            base_url=settings.wb_storefront_feedbacks_base_url,
            token="",
            timeout=settings.wb_http_timeout_seconds,
            # One retry: a storefront that refuses is not going to change its
            # mind inside the backoff ladder, and the next склейка is waiting.
            max_retries=1,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            rate_gate=storefront_feedbacks_rate_gate(settings),
        )

    async def fetch_rating(self, imt_id: int) -> WBStorefrontRating | None:
        """Fetch one склейка's rating summary.

        Args:
            imt_id: The склейка, from a review's ``productDetails.imtId``.

        Returns:
            The summary, or ``None`` when WB answered with an empty body.

        Raises:
            IntegrationError: On a transport failure or a body that is not the
                summary.
        """
        payload = await self._request(
            "GET", f"/feedbacks/v2/{imt_id}", rate_key=STOREFRONT_RATE_KEY
        )
        if payload is None:
            return None
        try:
            return WBStorefrontRating.model_validate(payload)
        except ValidationError as exc:
            raise IntegrationError(
                f"Unexpected storefront feedbacks shape for imt {imt_id}."
            ) from exc


__all__ = [
    "FEEDBACKS_PATH",
    "STOREFRONT_RATE_KEY",
    "FeedbackPage",
    "WBFeedbacksClient",
    "WBStorefrontFeedbacksClient",
]
