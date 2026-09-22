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
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.integrations.wildberries.schemas import WBOrderPrice, WBSaleRecord


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
            # `supplier/sales` is the harshest limiter WB exposes and ran UNPACED until
            # 2026-09-15. Its own entry in STATISTICS_ENDPOINT_BUCKETS keeps it off the
            # settlement report's 960-second default, which would stall every harvest.
            rate_gate=statistics_rate_gate(settings, token=token),
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

        The cursor is a timestamp only — the endpoint accepts no record-id
        component — so two hazards are handled client-side:

        * ``dateFrom`` is inclusive, and WB may re-stamp rows while we walk the
          pages, so consecutive pages can overlap. Records are keyed by
          ``saleID`` (the operation's unique id), keeping the freshest copy.
        * If a full page's max ``lastChangeDate`` does not advance past the
          cursor (>80 000 rows sharing one timestamp, or a misbehaving WB
          response), repeating the request would loop forever — that pass
          raises instead, so the harvest records the source as failed.

        Args:
            changed_since: Inclusive lower bound on ``lastChangeDate``.

        Returns:
            One :class:`WBSaleRecord` per item operation (sales and returns).

        Raises:
            IntegrationError: On an unexpected response shape, or when
                pagination stalls on a non-advancing cursor.
        """
        records: dict[str, WBSaleRecord] = {}
        cursor = changed_since.isoformat()
        previous_page_max: datetime | None = None
        while True:
            payload = await self._request(
                "GET", "/api/v1/supplier/sales", params={"dateFrom": cursor, "flag": 0}
            )
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected supplier/sales response shape (expected a list)."
                )
            page = [WBSaleRecord.model_validate(row) for row in payload]
            for record in page:
                records[record.sale_id] = record
            if len(page) < self._PAGE_LIMIT:
                break
            page_max = max(record.last_change_date for record in page)
            if previous_page_max is not None and page_max <= previous_page_max:
                raise IntegrationError(
                    "supplier/sales pagination stalled: a full page did not advance "
                    f"lastChangeDate past {previous_page_max.isoformat()}."
                )
            previous_page_max = page_max
            cursor = page_max.isoformat()
        return list(records.values())

    async def fetch_order_prices(self, *, changed_since: date | datetime) -> list[WBOrderPrice]:
        """Return ordered lines changed on or after a moment, for their prices only.

        Endpoint: ``GET /api/v1/supplier/orders``, the same feed shape and the
        same ``lastChangeDate`` cursor as :meth:`fetch_sales` — see there for
        why the walk keys rows and guards a non-advancing cursor.

        This exists because no seller API states the price a customer pays after
        WB's loyalty discount, and the storefront that did went behind an
        anti-bot challenge on 2026-09-22. The order line carries both bases
        (``priceWithDisc``, ``finishedPrice``) and the discount itself (``spp``),
        dated by the day the price applied.

        **Rows are read, never stored.** They become one day's price snapshot and
        are dropped; nothing here re-creates the order series that was removed.

        Args:
            changed_since: Inclusive lower bound on ``lastChangeDate``.

        Returns:
            One :class:`WBOrderPrice` per ordered line, cancellations included
            (the caller decides — a cancelled line still witnesses the price).

        Raises:
            IntegrationError: On an unexpected response shape, or when
                pagination stalls on a non-advancing cursor.
        """
        records: dict[str, WBOrderPrice] = {}
        cursor = changed_since.isoformat()
        previous_page_max: datetime | None = None
        while True:
            payload = await self._request(
                "GET", "/api/v1/supplier/orders", params={"dateFrom": cursor, "flag": 0}
            )
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected supplier/orders response shape (expected a list)."
                )
            page = [WBOrderPrice.model_validate(row) for row in payload]
            for record in page:
                records[record.srid] = record
            if len(page) < self._PAGE_LIMIT:
                break
            page_max = max(record.last_change_date for record in page)
            if previous_page_max is not None and page_max <= previous_page_max:
                raise IntegrationError(
                    "supplier/orders pagination stalled: a full page did not advance "
                    f"lastChangeDate past {previous_page_max.isoformat()}."
                )
            previous_page_max = page_max
            cursor = page_max.isoformat()
        return list(records.values())
