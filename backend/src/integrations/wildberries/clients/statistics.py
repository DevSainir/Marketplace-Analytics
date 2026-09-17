"""Low-level asynchronous WildBerries Statistics client.

The Statistics surface is the authoritative source for SALE-DATE attributed
buyouts and returns: one record per item operation, dated by the day the
customer accepted (or returned) the item — unlike the sales-funnel history,
whose ``buyoutCount`` is an order-date cohort that matures for weeks.
Authenticated with a dedicated "Статистика" token.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import statistics_rate_gate
from src.integrations.wildberries.schemas import WBOrderRecord, WBSaleRecord


@dataclass(frozen=True)
class WBOrderPage:
    """One page of the orders feed, and where the next one starts.

    Attributes:
        records: The page's order lines, deduplicated by ``srid``.
        next_cursor: ``lastChangeDate`` to ask from next, or ``None`` when the
            feed has no more pages.
    """

    records: list[WBOrderRecord]
    next_cursor: datetime | None


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

    async def fetch_orders_page(self, *, changed_since: date | datetime) -> WBOrderPage:
        """Return ONE page of ordered lines, and where the next page starts.

        Endpoint: ``GET /api/v1/supplier/orders`` with ``flag=0`` — ``dateFrom``
        filters on ``lastChangeDate``, so one call serves both the history walk
        and the nightly increment. Account-wide, ~1 request/minute, 80 000
        records a page.

        A page at a time, unlike :meth:`fetch_sales`, because this feed is
        walked over a кабинет's WHOLE history: the seller's first order to
        today is hundreds of thousands of lines, and a method that returned all
        of them would hold the lot in memory to hand back a list nobody wants
        whole. The caller persists each page and keeps the cursor.

        ``next_cursor`` is ``None`` when the page was not full — the feed is
        caught up. Otherwise it is the page's newest ``lastChangeDate``, and the
        next call repeats from there: the bound is inclusive, so pages overlap
        by whatever shares that timestamp, and ``srid`` deduplicates.

        Args:
            changed_since: Inclusive lower bound on ``lastChangeDate``.

        Returns:
            The page and its successor cursor.

        Raises:
            IntegrationError: On an unexpected response shape, or when a full
                page fails to advance the cursor — repeating that request would
                walk the same rows for ever.
        """
        payload = await self._request(
            "GET",
            "/api/v1/supplier/orders",
            params={"dateFrom": changed_since.isoformat(), "flag": 0},
        )
        if not isinstance(payload, list):
            raise IntegrationError("Unexpected supplier/orders response shape (expected a list).")
        records = {row["srid"]: WBOrderRecord.model_validate(row) for row in payload}
        page = list(records.values())
        if len(payload) < self._PAGE_LIMIT:
            return WBOrderPage(records=page, next_cursor=None)
        page_max = max(record.last_change_date for record in page)
        asked_from = (
            changed_since
            if isinstance(changed_since, datetime)
            else datetime.combine(changed_since, datetime.min.time())
        )
        if page_max.replace(tzinfo=None) <= asked_from.replace(tzinfo=None):
            raise IntegrationError(
                "supplier/orders pagination stalled: a full page did not advance "
                f"lastChangeDate past {asked_from.isoformat()}."
            )
        return WBOrderPage(records=page, next_cursor=page_max)
