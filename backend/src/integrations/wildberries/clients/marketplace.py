"""Asynchronous WildBerries Marketplace (FBS) client.

Wraps the two seller-warehouse endpoints on
``marketplace-api.wildberries.ru``. Both were verified live on 2026-08-13 with
a real "Marketplace" token.

Two behaviours that no amount of reading the docs would have told us:

* **The token category is the whole gate.** Every other scope answers this host
  with ``401 {"detail": "token scope not allowed"}`` — including "Supplies"
  (Supplies), whose own ``/api/v1/warehouses`` returns WB's acceptance directory and looks
  deceptively like the answer.
* **A read-only token is enough**, even though the stocks read is an HTTP POST.
"""

from __future__ import annotations

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import marketplace_rate_gate
from src.integrations.wildberries.schemas import WBFbsStockRow, WBFbsWarehouse


class WBMarketplaceClient(BaseWBClient):
    """Client for the WB Marketplace surface (seller-owned FBS warehouses)."""

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the marketplace client.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's "Marketplace"-scope bearer token. No other
                category authenticates this host.
        """
        super().__init__(
            base_url=settings.wb_marketplace_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            rate_gate=marketplace_rate_gate(settings, token=token),
        )

    async def fetch_warehouses(self) -> list[WBFbsWarehouse]:
        """Return every FBS warehouse the seller owns.

        Endpoint: ``GET /api/v3/warehouses``. Unlike most WB responses this one
        is a bare array, not an envelope.

        Returns:
            One :class:`WBFbsWarehouse` per seller warehouse (empty when the
            account runs no FBS).

        Raises:
            IntegrationError: On an unexpected response shape.
        """
        payload = await self._request("GET", "/api/v3/warehouses")
        if not isinstance(payload, list):
            raise IntegrationError(
                "Unexpected /api/v3/warehouses response shape (expected a JSON array)."
            )
        return [WBFbsWarehouse.model_validate(row) for row in payload if isinstance(row, dict)]

    async def fetch_stocks(self, *, warehouse_id: int, skus: list[str]) -> list[WBFbsStockRow]:
        """Return remaining units for ``skus`` at one FBS warehouse.

        Endpoint: ``POST /api/v3/stocks/{warehouseId}``, body ``{"skus": [...]}``
        — a read despite the verb, and the barcodes are the query, not a filter
        over some larger default set.

        **WB omits what it does not know.** Asking for 616 barcodes returned 296
        rows: the rest are not stocked at that warehouse at all. An absent
        barcode is therefore "not registered here", which is not the same fact
        as ``amount: 0`` ("registered, none left") — the caller decides how to
        treat each, and conflating them would invent stock history.

        Args:
            warehouse_id: WB id of the seller warehouse (``WBFbsWarehouse.id``).
            skus: Barcodes to ask about. Sending 616 in one request was accepted
                live, so no batching is applied below that.

        Returns:
            One :class:`WBFbsStockRow` per barcode WB knows at that warehouse.

        Raises:
            IntegrationError: On an unexpected response shape.
        """
        if not skus:
            return []
        payload = await self._request(
            "POST",
            f"/api/v3/stocks/{warehouse_id}",
            json_body={"skus": skus},
        )
        rows = payload.get("stocks") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise IntegrationError(
                "Unexpected /api/v3/stocks response shape (expected a 'stocks' array)."
            )
        return [WBFbsStockRow.model_validate(row) for row in rows if isinstance(row, dict)]
