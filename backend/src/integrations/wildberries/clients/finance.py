"""Low-level asynchronous WildBerries Finance/Realization client.

Wraps ``GET /api/v5/supplier/reportDetailByPeriod`` on the Statistics surface —
the authoritative source for settlement-dated logistics charges and the explicit
module's ``docs/finreports/DESIGN.md`` §3.D). Authenticated with the **«Статистика»** token
(NOT «Финансы» — verified live: the finance token returns "scope not allowed").

The report is settlement-dated (``rr_dt``) and paginates by an ``rrdid`` cursor
(the last row's ``rrd_id``); its rate limit matches the other statistics
surfaces (~1 req/min), so the raised backoff of :class:`WBStatisticsClient` is
the right precedent.
"""

from __future__ import annotations

from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.schemas import WBReportDetailRow


class WBFinanceClient(BaseWBClient):
    """Client for the WB realization/finance report (``reportDetailByPeriod``)."""

    #: WB caps one response at 100 000 rows; a full page means "repeat from the
    #: last row's ``rrd_id`` via the ``rrdid`` query cursor".
    _PAGE_LIMIT = 100_000

    def __init__(self, settings: Settings, *, token: str) -> None:
        """Build the finance client against the Statistics surface.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's «Статистика»-scope bearer token.
        """
        super().__init__(
            base_url=settings.wb_statistics_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries,
            # Match WBStatisticsClient: ~1 req/min surface, 429s carry no
            # Retry-After, so the shared 2/4/8/16s ladder is too tight.
            backoff_base_seconds=20.0,
            backoff_max_seconds=120.0,
        )

    async def fetch_report(self, *, date_from: date, date_to: date) -> list[WBReportDetailRow]:
        """Return every settlement row for the window, following the cursor.

        Endpoint: ``GET /api/v5/supplier/reportDetailByPeriod``. Pages by
        ``rrdid`` (the last row's ``rrd_id``) until a short page is returned. A
        full page whose last ``rrd_id`` does not advance would loop forever —
        that pass raises instead, so the harvest records the source as failed.

        Args:
            date_from: Inclusive settlement-date window start.
            date_to: Inclusive settlement-date window end.

        Returns:
            One :class:`WBReportDetailRow` per settlement operation.

        Raises:
            IntegrationError: On an unexpected response shape or a stalled cursor.
        """
        rows: dict[int, WBReportDetailRow] = {}
        cursor = 0
        previous_cursor: int | None = None
        while True:
            payload = await self._request(
                "GET",
                "/api/v5/supplier/reportDetailByPeriod",
                params={
                    "dateFrom": date_from.isoformat(),
                    "dateTo": date_to.isoformat(),
                    "rrdid": cursor,
                    "limit": self._PAGE_LIMIT,
                },
            )
            # WB returns null (not []) for an empty window — treat as "done".
            if payload is None:
                break
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected reportDetailByPeriod response shape (expected a list)."
                )
            page = [WBReportDetailRow.model_validate(row) for row in payload]
            for record in page:
                rows[record.rrd_id] = record
            if len(page) < self._PAGE_LIMIT:
                break
            next_cursor = page[-1].rrd_id
            if previous_cursor is not None and next_cursor <= previous_cursor:
                raise IntegrationError(
                    "reportDetailByPeriod pagination stalled: a full page did not "
                    f"advance rrd_id past {previous_cursor}."
                )
            previous_cursor = next_cursor
            cursor = next_cursor
        return list(rows.values())
