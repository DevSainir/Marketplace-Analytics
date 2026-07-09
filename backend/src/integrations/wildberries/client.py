"""Concrete asynchronous WildBerries API clients.

Each client targets one WB API surface, injects the correct bearer token, and
returns *typed raw* payloads (:mod:`.schemas`). All network I/O is async via
``httpx.AsyncClient`` inherited from :class:`BaseWBClient`.
"""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.base import BaseWBClient
from src.integrations.wildberries.schemas import (
    WBAdvCampaignStats,
    WBCampaign,
    WBCampaignGroup,
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

    def __init__(self, settings: Settings) -> None:
        """Build the analytics client from application settings."""
        super().__init__(
            base_url=settings.wb_analytics_base_url,
            token=settings.wb_analytics_token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
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


class WBAdvertisingClient(BaseWBClient):
    """Client for the WB Advertising surface (campaign full stats)."""

    def __init__(self, settings: Settings) -> None:
        """Build the advertising client from application settings."""
        super().__init__(
            base_url=settings.wb_advertising_base_url,
            token=settings.wb_advertising_token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=settings.wb_retry_backoff_seconds,
            backoff_max_seconds=settings.wb_retry_max_backoff_seconds,
        )

    #: Max campaign ids per fullstats request (WB caps the ``ids`` list).
    _FULLSTATS_BATCH = 50

    async def fetch_full_stats(
        self,
        *,
        campaign_ids: list[int],
        date_from: date,
        date_to: date,
    ) -> list[WBAdvCampaignStats]:
        """Fetch full advertising statistics for one or more campaigns.

        Endpoint: ``GET /adv/v3/fullstats``.

        Verified against the live WB API (2026-07): the query parameters are
        ``ids`` (comma-separated campaign ids), ``beginDate`` and ``endDate`` in
        ``YYYY-MM-DD`` format. Campaign ids are requested in batches of
        :attr:`_FULLSTATS_BATCH`; the response is a list with one entry per
        campaign that had activity in the window. Live constraints:

        * WB does **not** serve current-day statistics — requesting today's date
          returns HTTP 400 ("Invalid begin date"). Pass ``date_to`` no later
          than yesterday (Moscow time).
        * The maximum window is 31 days, and this surface is aggressively
          rate-limited (roughly one request per minute per seller).

        Args:
            campaign_ids: WB campaign identifiers (``ids`` param).
            date_from: Inclusive start date (Moscow time).
            date_to: Inclusive end date (Moscow time); must be <= yesterday.

        Returns:
            One :class:`WBAdvCampaignStats` per campaign that returned data.
        """
        results: list[WBAdvCampaignStats] = []
        for start in range(0, len(campaign_ids), self._FULLSTATS_BATCH):
            batch = campaign_ids[start : start + self._FULLSTATS_BATCH]
            params: dict[str, object] = {
                "ids": ",".join(str(cid) for cid in batch),
                "beginDate": date_from.isoformat(),
                "endDate": date_to.isoformat(),
            }
            payload = await self._request("GET", "/adv/v3/fullstats", params=params)
            # WB returns null (decoded as None) when no campaign in the batch
            # had activity in the window — a legitimately empty result.
            if payload is None:
                continue
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected fullstats response shape (expected a top-level "
                    f"list, got {type(payload).__name__})."
                )
            results.extend(WBAdvCampaignStats.model_validate(rec) for rec in payload if rec)
        return results

    async def list_campaigns(self) -> list[WBCampaign]:
        """List every advertising campaign with its type and status.

        Endpoint: ``GET /adv/v1/promotion/count`` (no params). WB groups
        campaigns by ``(type, status)``; this flattens the groups into one
        descriptor per campaign id. Campaign names are not available here.

        Returns:
            A flat list of :class:`WBCampaign` descriptors.
        """
        payload = await self._request("GET", "/adv/v1/promotion/count")
        if not isinstance(payload, dict):
            raise IntegrationError(
                "Unexpected promotion/count response shape (expected an object, "
                f"got {type(payload).__name__})."
            )
        # "adverts" is null when the account has no campaigns — legitimate.
        raw_groups = payload.get("adverts")
        groups = [WBCampaignGroup.model_validate(g) for g in raw_groups or []]
        return [
            WBCampaign(campaign_id=ref.advert_id, type=group.type, status=group.status)
            for group in groups
            for ref in group.advert_list
        ]
