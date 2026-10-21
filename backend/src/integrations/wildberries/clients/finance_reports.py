"""The realization report, on the surface WB actually maintains.

``GET /api/v5/supplier/reportDetailByPeriod`` — what the deleted
``clients/finance.py`` (``WBFinanceClient``) called until 2026-09-22 — was
announced for shutdown on **15 July 2026** and is absent from WB's current
documentation. It answered at one request per ~917 s and with escalating
multi-hour blocks that no official source describes; that is what a
switched-off endpoint looks like rather than a policy.

These three methods replace it, on ``finance-api.wildberries.ru`` with the
«Финансы» token, at **one request per minute each**, each its own bucket:

* :meth:`list_reports` — every report WB has formed, weekly or daily, with
  ``createDate`` served rather than derived, and WB's own totals per report.
* :meth:`stream_report_rows` — the detail rows of ONE report, paged by
  ``rrdId``.
* :meth:`stream_rows_by_period` — the same rows for a settlement period,
  several reports to a page.

Two consequences worth stating, because they retired machinery rather than
sped it up.

**Discovery stops competing with fetching.** The list is a separate bucket, so
«is there a new report» no longer spends the budget that fetching one needs —
which is the whole problem the publication calendar
(``finreports/services/publication.py``, deleted 2026-09-23) was built to avoid
by arithmetic.

**The forward walk is by report, not by date window.** The old endpoint took a
period and the walk cut it into weeks because a week was one report's worth;
here the report id IS the unit, so a report either is complete or is not. A
seller on WB's forum documented that ``rrd_id`` is not monotonic by date across
report boundaries on the by-period method — paging one report at a time
removes that hazard too.

:meth:`stream_rows_by_period` has one caller, the history backfill's window
walk (``tasks/settlement/window.py``), and only for a RUN of consecutive owed
reports: one request there is worth eight to twenty-one by id. Risk 5 was
measured on 2026-09-23 and not reproduced, and the window books nothing until
every page has landed, so an early stop leaves its reports missing rather than
booked.

See ``docs/finreports/MIGRATION_TO_FINANCE_V1.md``.
"""

from __future__ import annotations

import enum
from collections.abc import AsyncGenerator
from datetime import date

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.endpoints import (
    SALES_REPORTS_BY_PERIOD_PATH,
    SALES_REPORTS_DETAILED_PATH,
    SALES_REPORTS_LIST_PATH,
    sales_report_detail_path,
)
from src.integrations.wildberries.rate_limit import RateGate, finance_reports_rate_gate
from src.integrations.wildberries.schemas.finance import (
    WBFinanceReportHeader,
    WBFinanceReportRow,
)


class ReportPeriod(enum.StrEnum):
    """Which periodicity of realization report to ask WB for.

    WB forms both, on the same methods, and ``period`` **defaults to weekly** —
    which is why this service read only the weekly half of the surface from the
    migration on 2026-09-22 until 2026-09-23. Verified live on «Демо»: the
    two lanes are the same rows with the same ``rrdId``, cut at a different
    boundary, and a single-day window asked *without* this parameter answers 204
    rather than an error, so the mistake looks exactly like «WB has not formed
    the report yet».

    ``detailed/{reportId}`` takes no periodicity: the report id carries it.
    """

    WEEKLY = "weekly"
    DAILY = "daily"


class WBFinanceReportsClient(BaseWBClient):
    """Client for WB's realization reports on the Finance surface."""

    #: Named rather than derived from the class name, which would give
    #: «financereports». The metric label and the rate bucket's surface key
    #: have to read as the same thing, and WB calls it «Финансы».
    WB_SURFACE = "finance"

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

    async def list_reports(
        self, *, date_from: date, date_to: date, period: ReportPeriod = ReportPeriod.WEEKLY
    ) -> list[WBFinanceReportHeader]:
        """Return every report WB has formed whose period falls in the window.

        The method the old surface had no equivalent of. It answers «is there a
        report we do not hold» outright — no probe row, no period arithmetic —
        and carries WB's own totals, which is the first thing the P&L can be
        checked against (``docs/finreports/PNL.md`` warns that most ways to get
        a settlement figure wrong produce a plausible statement, not an error).

        Args:
            date_from: Inclusive start of the window to list.
            date_to: Inclusive end.
            period: Which periodicity to list. WB's default is weekly, and this
                service read only that until 2026-09-23 — see
                :class:`ReportPeriod`.

        Returns:
            The report headers, in WB's order. Empty when WB has formed none.

        Raises:
            IntegrationError: On a refused gate, an exhausted ladder, or an
                unexpected payload shape.
        """
        body: dict[str, object] = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
        }
        # Sent only for the daily lane, so the weekly request stays byte-for-byte
        # the one this service has been making all along. `weekly` is WB's
        # documented default and we have measured the daily value; we have never
        # measured what a *fleet* of sellers does with an explicitly weekly one,
        # and the settlement history is not the place to find out.
        if period is not ReportPeriod.WEEKLY:
            body["period"] = period.value
        payload = await self._request(
            "POST",
            SALES_REPORTS_LIST_PATH,
            json_body=body,
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

    async def stream_rows_by_period(
        self,
        *,
        date_from: date,
        date_to: date,
        cursor: int = 0,
        reserve_seconds: float = 0.0,
    ) -> AsyncGenerator[list[WBFinanceReportRow], None]:
        """The same rows, addressed by settlement period rather than report id.

        For the history backfill's window walk, over a run of consecutive owed
        reports, where one request replaces eight to twenty-one by id. The
        forward harvest stays on :meth:`stream_report_rows`. A seller on WB's
        forum documented ``rrdId`` going non-monotonic across report boundaries
        on this form; measured on 2026-09-23 it did not, and the window books
        nothing until every page has landed, so a walk that stopped early would
        leave its reports missing rather than booked.

        Args:
            date_from: Inclusive settlement-date window start.
            date_to: Inclusive settlement-date window end.
            cursor: ``rrdId`` to page from; 0 for the first page.
            reserve_seconds: Non-zero marks this as background work that yields
                its window to anything a person is waiting on.

        Yields:
            Batches of at most :data:`_STREAM_BATCH` validated rows.
        """
        async for raw in self._stream_json_items(
            "POST",
            SALES_REPORTS_BY_PERIOD_PATH,
            json_body={
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "limit": self._STREAM_LIMIT,
                "rrdId": cursor,
            },
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
