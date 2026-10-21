"""Low-level asynchronous WildBerries Prices & Discounts client.

The Prices & Discounts surface is the authoritative source for the account's
*seller* prices — specifically ``discountedPrice`` (the price after the seller's
own discount), which the monitoring SPP and order/buyout ₽ volumes are computed
from. Authenticated with a dedicated "Цены и скидки" token.
"""

from __future__ import annotations

from typing import Any

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import catalogue_rate_gate
from src.integrations.wildberries.schemas import WBPriceGood


class WBPricesClient(BaseWBClient):
    """Client for the WB Prices & Discounts surface (seller prices)."""

    #: WB caps the goods-filter page at 1000 records; paginate by offset.
    _GOODS_PAGE = 1000

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the prices client.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's "Цены и скидки"-scope bearer token.
        """
        super().__init__(
            # Prices API. Same measured bucket as content (2026-09-15); one call per
            # harvest, but it shared the unpaced fate of the rest of this family.
            rate_gate=catalogue_rate_gate(settings, token=token, surface="prices"),
            base_url=settings.wb_prices_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
        )

    async def fetch_prices(self) -> list[WBPriceGood]:
        """Return every SKU's seller pricing record for the account.

        Endpoint: ``GET /api/v2/list/goods/filter`` (paginated by ``offset``,
        ``limit`` up to :attr:`_GOODS_PAGE`). Verified doc shape (2026-07):
        ``{"data": {"listGoods": [{nmID, discount, sizes:[{discountedPrice,
        ...}]}, ...]}}``. This surface allows ~10 requests / 6 seconds; the
        shared retry/backoff honours any 429 ``Retry-After``.

        Returns:
            One :class:`WBPriceGood` per SKU on the account.
        """
        goods: list[WBPriceGood] = []
        offset = 0
        while True:
            params: dict[str, Any] = {"limit": self._GOODS_PAGE, "offset": offset}
            payload = await self._request("GET", "/api/v2/list/goods/filter", params=params)
            # A malformed 200 must raise, not default to an empty page: the
            # harvest would otherwise record a silent zero-price snapshot.
            data = payload.get("data") if isinstance(payload, dict) else None
            rows = data.get("listGoods") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise IntegrationError(
                    "Unexpected goods/filter response shape (expected data.listGoods list)."
                )
            goods.extend(WBPriceGood.model_validate(row) for row in rows)
            if len(rows) < self._GOODS_PAGE:
                break
            offset += self._GOODS_PAGE
        return goods
