"""Low-level asynchronous WildBerries Statistics client.

The Statistics surface is the authoritative source for SALE-DATE attributed
buyouts and returns: one record per item operation, dated by the day the
customer accepted (or returned) the item — unlike the sales-funnel history,
whose ``buyoutCount`` is an order-date cohort that matures for weeks.
Authenticated with a dedicated "Статистика" token.
"""

from __future__ import annotations

from datetime import date, datetime

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.base import BaseWBClient
from src.integrations.wildberries.schemas import WBSaleRecord


class WBStatisticsClient(BaseWBClient):
    """Client for the WB Statistics surface (per-sale buyout/return records)."""

    #: WB caps one response at 80 000 records; a full page means "repeat from
    #: the last row's lastChangeDate".
    _PAGE_LIMIT = 80_000

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the statistics client.

        The backoff base/max are raised above the shared defaults: this
        surface enforces ~1 request/minute and its 429s carry NO Retry-After
        header, so the default 2/4/8/16s ladder (30s total) would exhaust all
        retries inside a single limiter window.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's "Статистика"-scope bearer token.
        """
        super().__init__(
            base_url=settings.wb_statistics_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            backoff_base_seconds=20.0,
            backoff_max_seconds=120.0,
        )

    async def fetch_sales(self, *, changed_since: date | datetime) -> list[WBSaleRecord]:
        """Return every sale/return record changed on or after a moment.

        Endpoint: ``GET /api/v1/supplier/sales`` with ``flag=0`` — ``dateFrom``
        filters on ``lastChangeDate``, so the same call is both the initial
        backfill (an early date) and the nightly increment (the harvest window
        start): a return processed today for a months-old sale carries today's
        ``lastChangeDate`` and is always picked up. Account-wide (no SKU
        filter). Rate limit ~1 request/minute; the shared retry/backoff honours
        the 429 ``Retry-After``. Responses cap at 80 000 records — a full page
        repeats the request from the last row's ``lastChangeDate``.

        Args:
            changed_since: Inclusive lower bound on ``lastChangeDate``.

        Returns:
            One :class:`WBSaleRecord` per item operation (sales and returns).
        """
        records: list[WBSaleRecord] = []
        cursor = changed_since.isoformat()
        while True:
            payload = await self._request(
                "GET", "/api/v1/supplier/sales", params={"dateFrom": cursor, "flag": 0}
            )
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected supplier/sales response shape (expected a list)."
                )
            page = [WBSaleRecord.model_validate(row) for row in payload]
            records.extend(page)
            if len(page) < self._PAGE_LIMIT:
                break
            cursor = max(record.last_change_date for record in page).isoformat()
        return records
