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

    #: Rows the freshness probe asks for. It only needs to know whether the
    #: window is empty, so one row is the whole answer.
    _PROBE_LIMIT = 1

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

    async def fetch_first_row(self, *, date_from: date, date_to: date) -> WBReportDetailRow | None:
        """Return the window's first settlement row, or ``None`` if WB has none.

        The freshness probe behind the harvest's gate: asked over a window that
        starts the day after everything already harvested, a single row is proof
        that WB has published a report we do not hold, and an empty answer is
        proof that it has not. One page of one row, so the gate costs one request
        against a ~1 req/min surface instead of the full paginated walk.

        Args:
            date_from: Inclusive settlement-date window start.
            date_to: Inclusive settlement-date window end.

        Returns:
            The first row WB serves for the window (whose ``realizationreport_id``
            and ``create_dt`` name the new report), or ``None`` when the window is
            empty.

        Raises:
            IntegrationError: On an unexpected response shape.
        """
        payload = await self._request(
            "GET",
            "/api/v5/supplier/reportDetailByPeriod",
            params={
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "rrdid": 0,
                "limit": self._PROBE_LIMIT,
            },
        )
        # Verified live (2026-08-04): an empty window answers 204 No Content, not
        # a 200 with ``[]``, so the "no new report" signal arrives as a decoded
        # ``None``. A probe that only checked for an empty list would read every
        # quiet day as an error.
        if payload is None:
            return None
        if not isinstance(payload, list):
            raise IntegrationError(
                "Unexpected reportDetailByPeriod response shape (expected a list)."
            )
        if not payload:
            return None
        return WBReportDetailRow.model_validate(payload[0])

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
