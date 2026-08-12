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

from collections.abc import AsyncGenerator
from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.schemas import WBReportDetailRow


class WBFinanceClient(BaseWBClient):
    """Client for the WB realization/finance report (``reportDetailByPeriod``)."""

    #: Rows asked for per request. **This is a memory ceiling, not a throughput
    #: knob.** WB allows up to 100 000, and asking for that many is what
    #: OOM-killed the 2026-08-11 harvest: a settlement row costs ~9.7 KB while
    #: it is being validated (measured — the raw decoded dict and the
    #: :class:`WBReportDetailRow` coexist), so a full page is ~1 GB of transient
    #: heap and the caller has no way to process it in smaller bites.
    #:
    #: At 10 000 a page costs ~125 MB including the undecoded response body,
    #: and :meth:`iter_report_pages` hands it over before asking for the next —
    #: so the peak is fixed by this constant rather than by how much the seller
    #: sold. The price is more requests against a ~1 req/min surface (a 28-day
    #: window of ~40 000 rows costs 5 instead of 1), which the harvest can
    #: afford and an OOM kill is not.
    _PAGE_LIMIT = 10_000

    #: Rows the freshness probe asks for. It only needs to know whether the
    #: window is empty, so one row is the whole answer.
    _PROBE_LIMIT = 1

    def __init__(self, settings: Settings, *, token: str, max_retries: int | None = None) -> None:
        """Build the finance client against the Statistics surface.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's «Статистика»-scope bearer token.
            max_retries: Override for the retry ladder. The harvest lowers it
                because it pages **inside an open transaction** — see
                :func:`~src.modules.finreports.tasks.harvest.harvest_workspace`.
        """
        super().__init__(
            base_url=settings.wb_statistics_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries if max_retries is None else max_retries,
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

    async def iter_report_pages(
        self, *, date_from: date, date_to: date
    ) -> AsyncGenerator[list[WBReportDetailRow], None]:
        """Yield the window's settlement rows one ``rrdid`` page at a time.

        Endpoint: ``GET /api/v5/supplier/reportDetailByPeriod``. Pages by
        ``rrdid`` (the last row's ``rrd_id``) until a short page is returned. A
        full page whose last ``rrd_id`` does not advance would loop forever —
        that pass raises instead, so the harvest records the source as failed.

        **Nothing accumulates across pages.** This used to return the whole
        window as one list, which made the caller's peak memory a function of
        how much the seller sold — it grew on its own until it crossed the
        worker's cgroup limit and the 2026-08-11 harvest was killed mid-walk.
        The generator holds at most one page (:data:`_PAGE_LIMIT` rows), so a
        caller that ingests each page as it arrives has a peak fixed by that
        constant. The cursor state that survives a page is two integers.

        Args:
            date_from: Inclusive settlement-date window start.
            date_to: Inclusive settlement-date window end.

        Yields:
            Non-empty pages of :class:`WBReportDetailRow`, in WB's own
            ``rrd_id`` order. Pages do not overlap: the cursor is exclusive, so
            a row is yielded exactly once.

        Raises:
            IntegrationError: On an unexpected response shape or a stalled cursor.
        """
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
                return
            if not isinstance(payload, list):
                raise IntegrationError(
                    "Unexpected reportDetailByPeriod response shape (expected a list)."
                )
            page_size = len(payload)
            page = _validate_draining(payload)
            # ``payload`` is now empty, but the name still pins the (already
            # freed) list in this frame across the yield below. Dropping it
            # keeps the generator's retained set to the validated page alone.
            del payload
            if page:
                yield page
            if page_size < self._PAGE_LIMIT:
                return
            next_cursor = page[-1].rrd_id
            if previous_cursor is not None and next_cursor <= previous_cursor:
                raise IntegrationError(
                    "reportDetailByPeriod pagination stalled: a full page did not "
                    f"advance rrd_id past {previous_cursor}."
                )
            previous_cursor = next_cursor
            cursor = next_cursor
            del page


def _validate_draining(payload: list[object]) -> list[WBReportDetailRow]:
    """Validate a decoded page, freeing each raw row as it is converted.

    A list comprehension over ``payload`` would hold the whole page twice at
    once — the decoded dicts and the models built from them. Measured on a
    realistic settlement row that is 13.5 KB per row instead of 9.7 KB, i.e.
    ~40 % of the page's peak for no reason: the raw dict is dead the moment its
    model exists. Draining from the end (``pop`` is O(1)) drops each one
    immediately; the result is reversed back into WB's order, which the cursor
    depends on.

    Args:
        payload: The decoded JSON page. **Emptied by this call.**

    Returns:
        The validated rows in their original order.
    """
    rows: list[WBReportDetailRow] = []
    while payload:
        rows.append(WBReportDetailRow.model_validate(payload.pop()))
    rows.reverse()
    return rows
