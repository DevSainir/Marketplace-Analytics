"""The realization report, on the surface WB actually maintains.

``GET /api/v5/supplier/reportDetailByPeriod`` — what
:mod:`src.integrations.wildberries.clients.finance` calls — was announced for
shutdown on **15 July 2026** and is absent from WB's current documentation. It
still answers, at one request per ~917 s and with escalating multi-hour blocks
that no official source describes; that is what a switched-off endpoint looks
like rather than a policy.

These two methods replace it, on ``finance-api.wildberries.ru`` with the
«Финансы» token, at **one request per minute each**:

* :meth:`list_reports` — every report WB has formed, with ``createDate`` served
  rather than derived, and WB's own totals per report.
* :meth:`stream_report_rows` — the detail rows of ONE report, paged by
  ``rrdId``.

Two consequences worth stating, because they retire machinery rather than
speed it up.

**Discovery stops competing with fetching.** The list is a separate bucket, so
«is there a new report» no longer spends the budget that fetching one needs —
which is the whole problem
:mod:`src.modules.finreports.services.publication` was built to avoid by
arithmetic.

**The walk is by report, not by date window.** The old endpoint took a period
and the walk cut it into weeks because a week was one report's worth; here the
report id IS the unit, so a window that half-completes is not a state that can
exist. A seller on WB's forum documented that ``rrd_id`` is not monotonic by
date across report boundaries on the by-period method — paging one report at a
time removes that hazard too.

See ``docs/finreports/MIGRATION_TO_FINANCE_V1.md``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_DETAILED_PATH,
    SALES_REPORTS_LIST_PATH,
    sales_report_detail_path,
)
from src.integrations.wildberries.rate_limit import RateGate, finance_reports_rate_gate
from src.integrations.wildberries.schemas.finance import (
    WBFinanceReportHeader,
    WBFinanceReportRow,
)


class WBFinanceReportsClient(BaseWBClient):
    """Client for WB's realization reports on the Finance surface."""

    #: Rows asked for per request. WB's documented maximum, and affordable only
    #: because the body is parsed as it arrives — decoding a 100 000-row page
    #: whole is ~1.25 GB against a 768 MiB worker.
    _STREAM_LIMIT = 100_000

    #: Rows handed to the caller at a time, and therefore the real memory
    #: ceiling of a streamed walk. Same figure the old client used, for the
    #: same reason: the batch, not the page, is what has to fit.
    _STREAM_BATCH = 2_000

    def __init__(
        self,
        settings: Settings,
        *,
        token: str,
        max_retries: int | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        """Build the client against the Finance surface.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's «Финансы»-scope bearer token.
            max_retries: Override for the retry ladder.
            rate_gate: Pacing gate override, for tests.
        """
        super().__init__(
            base_url=settings.wb_finance_base_url,
            token=token,
            timeout=settings.wb_http_timeout_seconds,
            max_retries=settings.wb_max_retries if max_retries is None else max_retries,
            # A minute between requests, so the shared 2/4/8/16 s ladder is
            # far too tight to be useful and the gate is what does the work.
            backoff_base_seconds=20.0,
            backoff_max_seconds=120.0,
            rate_gate=rate_gate or finance_reports_rate_gate(settings, token=token),
            # Anything past a minute is the next tick's problem, not a wait to
            # sleep off inside a task holding the fleet lock.
            retry_after_ceiling_seconds=70.0,
        )

    async def list_reports(self, *, date_from: date, date_to: date) -> list[WBFinanceReportHeader]:
        """Return every report WB has formed whose period falls in the window.

        The method the old surface had no equivalent of. It answers «is there a
        report we do not hold» outright — no probe row, no period arithmetic —
        and carries WB's own totals, which is the first thing the P&L can be
        checked against (``docs/finreports/PNL.md`` warns that most ways to get
        a settlement figure wrong produce a plausible statement, not an error).

        Args:
            date_from: Inclusive start of the window to list.
            date_to: Inclusive end.

        Returns:
            The report headers, in WB's order. Empty when WB has formed none.

        Raises:
            IntegrationError: On a refused gate, an exhausted ladder, or an
                unexpected payload shape.
        """
        payload = await self._request(
            "POST",
            SALES_REPORTS_LIST_PATH,
            json_body={"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
        )
        if payload is None:
            return []
        if not isinstance(payload, list):
            raise IntegrationError(
                f"WildBerries returned {type(payload).__name__} for the report list, "
                "expected a list."
            )
        return [WBFinanceReportHeader.model_validate(item) for item in payload]

    @property
    def stream_limit(self) -> int:
        """Rows a streamed request asks WB for — the caller's short-page test."""
        return self._STREAM_LIMIT

    async def stream_report_rows(
        self,
        *,
        report_id: int,
        cursor: int = 0,
        reserve_seconds: float = 0.0,
    ) -> AsyncGenerator[list[WBFinanceReportRow], None]:
        """Stream ONE request's worth of one report's rows, never holding a page.

        One request, not a walk: the caller keeps the ``rrdId`` cursor and
        decides whether to ask again, because between pages is where it commits
        a transaction.

        Args:
            report_id: WB's ``reportId``, from :meth:`list_reports`.
            cursor: ``rrdId`` to page from; 0 for the first page. Exclusive, so
                a row is returned exactly once across a walk.
            reserve_seconds: Non-zero marks this as background work that yields
                its window to anything a person is waiting on.

        Yields:
            Batches of at most :data:`_STREAM_BATCH` validated rows, in WB's
            own ``rrdId`` order.

        Raises:
            IntegrationError: On a refused gate, an exhausted retry ladder, a
                malformed body, or an unexpected row shape.
        """
        async for raw in self._stream_json_items(
            "POST",
            sales_report_detail_path(report_id),
            json_body={"limit": self._STREAM_LIMIT, "rrdId": cursor},
            # Every report id is the same WB method and the same WB bucket.
            # Left to default to the path, each report would get its own empty
            # bucket and nothing would be paced.
            rate_key=SALES_REPORTS_DETAILED_PATH,
            batch_size=self._STREAM_BATCH,
            reserve_seconds=reserve_seconds,
        ):
            yield _validate_draining(raw)


def _validate_draining(payload: list[object]) -> list[WBFinanceReportRow]:
    """Validate a decoded page, freeing each raw row as it is converted.

    A comprehension would hold the decoded dicts and the models at once —
    ~40 % more peak for no reason, measured on the old surface's identical
    rows. Draining from the end drops each dict the moment its model exists;
    the result is reversed back into WB's order, which the cursor depends on.

    Args:
        payload: The decoded JSON page. **Emptied by this call.**

    Returns:
        The validated rows in their original order.
    """
    rows: list[WBFinanceReportRow] = []
    while payload:
        rows.append(WBFinanceReportRow.model_validate(payload.pop()))
    rows.reverse()
    return rows
