"""Low-level asynchronous WildBerries Content API client.

The Content API is the authoritative source for the account's product catalogue
(nmID -> card metadata). The Monitoring harvest uses it to discover *which* SKUs
to pull funnel + stock for. Authenticated with the analytics token.
"""

from __future__ import annotations

from typing import Any

from src.core.config import Settings
from src.integrations.wildberries.base import BaseWBClient
from src.integrations.wildberries.schemas import WBCard

#: Max cards per cards/list page (WB cursor pagination).
_CARDS_PAGE = 100


class WBContentClient(BaseWBClient):
    """Client for the WB Content surface (product cards)."""

    def __init__(self, settings: Settings) -> None:
        """Build the content client from application settings."""
        super().__init__(
            base_url=settings.wb_content_base_url,
            token=settings.wb_analytics_token,
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
            raw_cards = payload.get("cards", []) if isinstance(payload, dict) else []
            cards.extend(WBCard.model_validate(card) for card in raw_cards)

            cur = payload.get("cursor", {}) if isinstance(payload, dict) else {}
            if int(cur.get("total", 0)) < _CARDS_PAGE:
                break
            cursor = {
                "limit": _CARDS_PAGE,
                "updatedAt": cur["updatedAt"],
                "nmID": cur["nmID"],
            }
        return cards

    async def list_all_nm_ids(self) -> list[int]:
        """Return every nmID on the account.

        Thin wrapper over :meth:`fetch_all_cards` for callers that only need the
        SKU identifiers (e.g. the harvest's funnel/stock fan-out).

        Returns:
            The full list of SKU identifiers for the account.
        """
        return [card.nm_id for card in await self.fetch_all_cards()]
