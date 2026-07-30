"""Asynchronous WildBerries Seller Analytics client (funnel + stocks).

Injects the workspace's Analytics-scope bearer token and returns *typed raw*
payloads (:mod:`src.integrations.wildberries.schemas`). All network I/O is
async via ``httpx.AsyncClient`` inherited from :class:`BaseWBClient`.
"""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import analytics_rate_gate
from src.integrations.wildberries.schemas import (
    WBFunnelAggregateRow,
    WBFunnelHistoryRow,
    WBStockRow,
)

# NOTE on shape validation: a 200 response whose body does not match the
# verified live shape (WB error envelope, silent contract change) must raise
# IntegrationError — defaulting to an empty list would let the harvest report
# "success" with zero rows, silently punching holes in the time series.


class WBAnalyticsClient(BaseWBClient):
    """Client for the WB Seller Analytics surface (funnel + stocks)."""

    #: WB caps the funnel-history endpoint at 20 nmIDs per request.
    _FUNNEL_BATCH = 20

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the analytics client.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's Analytics-scope bearer token (tokens are
                per-workspace, stored encrypted in the database).
        """
        super().__init__(
            base_url=settings.wb_analytics_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
            # This surface is the one that took the site's funnel data out on
            # 2026-07-30: its buckets are small, and overrunning them makes WB
            # stall the connection rather than answer 429. Pace before sending.
            rate_gate=analytics_rate_gate(settings, token=token),
        )

    async def fetch_sales_funnel(
        self,
        *,
        nm_ids: list[int],
        date_from: date,
        date_to: date,
    ) -> list[WBFunnelHistoryRow]:
        """Fetch the DAILY organic sales-funnel history for the given SKUs.

        Endpoint: ``POST /api/analytics/v3/sales-funnel/products/history``.

        Verified against the live WB API (2026-07): the body requires **both**
        ``nmIds`` (note the lowercase spelling on this endpoint) and
        ``selectedPeriod`` with ``start``/``end`` keys (``YYYY-MM-DD``). The
        response is a top-level list, one node per product, each carrying a
        per-day ``history`` array — the true daily series the normalization
        pipeline needs.

        WB rejects more than :attr:`_FUNNEL_BATCH` nmIDs per request, so the SKU
        list is transparently chunked; the shared retry/backoff handles this
        endpoint's rate limiter between chunks.

        Args:
            nm_ids: SKU (``nmId``) identifiers to request (any length).
            date_from: Inclusive period start (Moscow time).
            date_to: Inclusive period end (Moscow time).

        Returns:
            A list of per-product rows, each holding its daily ``history``.
        """
        results: list[WBFunnelHistoryRow] = []
        for offset in range(0, len(nm_ids), self._FUNNEL_BATCH):
            batch = nm_ids[offset : offset + self._FUNNEL_BATCH]
            body: dict[str, object] = {
                "nmIds": batch,
                "selectedPeriod": {
                    "start": date_from.isoformat(),
                    "end": date_to.isoformat(),
                },
            }
            payload = await self._request(
                "POST",
                "/api/analytics/v3/sales-funnel/products/history",
                json_body=body,
            )
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected sales-funnel response shape (expected a top-level "
                    f"list, got {type(payload).__name__})."
                )
            results.extend(WBFunnelHistoryRow.model_validate(item) for item in payload)
        return results

    async def fetch_funnel_cohort_day(self, *, day: date) -> list[WBFunnelAggregateRow]:
        """Fetch every SKU's matured buyout/cancel cohort for a single day.

        Endpoint: ``POST /api/analytics/v3/sales-funnel/products`` (the period
        aggregate), called with ``start == end == day``.

        This is the ONLY source of ``cancelCount``, and the only funnel surface
        that serves a period older than 7 days — the daily history feed rejects
        it (HTTP 400 "invalid start day: excess limit on days"). Since a
        cohort's deliveries keep maturing for ~3 weeks, re-reading an old day
        here is what keeps «Процент выкупа» converging on WB's own figure
        instead of freezing at the value it had 7 days after the order.

        Verified live (2026-07-16): the ``nmIDs`` body filter is IGNORED — WB
        returns the seller's whole catalogue in one page regardless — so no
        SKU list is sent and the caller filters the rows it cares about.

        Args:
            day: The order-date cohort to read (Moscow time).

        Returns:
            One row per product in the seller's catalogue.

        Raises:
            IntegrationError: If the response does not match the verified shape.
        """
        # ``limit`` defaults to 50 per the official spec (max 1000): without it
        # a catalogue past 50 SKUs would silently truncate — and a truncated
        # cohort pass reads as "no orders that day" for the missing SKUs.
        body: dict[str, object] = {
            "selectedPeriod": {"start": day.isoformat(), "end": day.isoformat()},
            "limit": 1000,
        }
        payload = await self._request(
            "POST",
            "/api/analytics/v3/sales-funnel/products",
            json_body=body,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("products") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise IntegrationError(
                "Unexpected sales-funnel aggregate response shape (expected data.products list)."
            )
        return [WBFunnelAggregateRow.model_validate(item) for item in rows]

    async def fetch_warehouse_stocks(
        self,
        *,
        nm_ids: list[int],
    ) -> list[WBStockRow]:
        """Fetch remaining stock quantities per warehouse.

        Endpoint: ``POST /api/analytics/v1/stocks-report/wb-warehouses``.

        Args:
            nm_ids: SKU identifiers to request stock levels for.

        Returns:
            A flat list of per-warehouse stock snapshots.
        """
        body: dict[str, object] = {"nmIds": nm_ids}
        payload = await self._request(
            "POST",
            "/api/analytics/v1/stocks-report/wb-warehouses",
            json_body=body,
        )
        # Verified live shape: {"data": {"items": [ {nmId, warehouseName,
        # quantity, ...}, ... ]}}.
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("items") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise IntegrationError(
                "Unexpected stocks-report response shape (expected data.items list)."
            )
        return [WBStockRow.model_validate(item) for item in rows]
