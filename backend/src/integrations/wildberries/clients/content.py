"""Low-level asynchronous WildBerries Content API client.

The Content API is the authoritative source for the account's product catalogue
(nmID -> card metadata). The Monitoring harvest uses it to discover *which* SKUs
to pull funnel + stock for. Authenticated with the analytics token.
"""

from __future__ import annotations

from typing import Any

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.schemas import WBCard

#: Max cards per cards/list page (WB cursor pagination).
_CARDS_PAGE = 100


class WBContentClient(BaseWBClient):
    """Client for the WB Content surface (product cards)."""

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the content client.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's Analytics-scope bearer token (the Content
                surface accepts it; no separate content token exists).
        """
        super().__init__(
            base_url=settings.wb_content_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
        )

    async def fetch_all_cards(self) -> list[WBCard]:
        """Return every product card on the account (identity + sizes).

        Endpoint: ``POST /content/v2/get/cards/list``, walked via WB's cursor
        pagination (``updatedAt`` + ``nmID``) until a short page is returned.
        Each card carries its ``vendorCode``/``title`` and per-size ``chrtID`` +
        human ``techSize`` label — the authoritative source for the vendor code
        and size dimensions the label-less funnel/stock feeds lack.

        Returns:
            The full list of parsed product cards for the account.
        """
        cards: list[WBCard] = []
        cursor: dict[str, Any] = {"limit": _CARDS_PAGE}
        while True:
            body: dict[str, Any] = {"settings": {"cursor": cursor, "filter": {"withPhoto": -1}}}
            payload = await self._request("POST", "/content/v2/get/cards/list", json_body=body)
            # A malformed 200 must raise, not default to an empty page: the
            # harvest discovers its SKU list from this call, so a silent empty
            # result would skip the entire account without any error signal.
            if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
                raise IntegrationError(
                    "Unexpected cards/list response shape (expected an object with a 'cards' list)."
                )
            raw_cards = payload["cards"]
            cards.extend(WBCard.model_validate(card) for card in raw_cards)

            cur = payload.get("cursor")
            if not isinstance(cur, dict):
                raise IntegrationError(
                    "Unexpected cards/list response shape (missing 'cursor' object)."
                )
            if int(cur.get("total", 0)) < _CARDS_PAGE:
                break
            if "updatedAt" not in cur or "nmID" not in cur:
                # A full page with no continuation keys would otherwise be an
                # opaque KeyError killing the whole harvest mid-pagination.
                raise IntegrationError(
                    "cards/list cursor lacks 'updatedAt'/'nmID' on a full page; "
                    "cannot continue pagination."
                )
            cursor = {
                "limit": _CARDS_PAGE,
                "updatedAt": cur["updatedAt"],
                "nmID": cur["nmID"],
            }
        return cards

    async def upload_media_file(
        self,
        *,
        nm_id: int,
        photo_number: int,
        content: bytes,
        filename: str,
        content_type: str,
    ) -> None:
        """Replace one media slot of a card with an uploaded file.

        Endpoint: ``POST /content/v3/media/file`` — multipart, with the target
        card and slot in headers rather than the body.

        This is deliberately not ``/content/v3/media/save``: that method takes a
        list of URLs and **replaces the entire gallery**, so setting the main
        photo with it means re-sending every other image and losing any it does
        not know about. ``media/file`` writes exactly one slot, which is what a
        photo rotation needs — ``photo_number=1`` is the main photo.

        WB moderates the new image asynchronously; a 200 here means accepted for
        moderation, not yet live on the storefront.

        Args:
            nm_id: WB SKU whose gallery slot is written.
            photo_number: 1-based slot; ``1`` is the main photo.
            content: Raw image bytes.
            filename: Name to send in the multipart part (WB ignores it, but a
                missing one makes some proxies drop the part).
            content_type: MIME type of ``content``.

        Raises:
            IntegrationError: If WB rejects the upload.
        """
        await self._request(
            "POST",
            "/content/v3/media/file",
            headers={"X-Nm-Id": str(nm_id), "X-Photo-Number": str(photo_number)},
            files={"uploadfile": (filename, content, content_type)},
        )
