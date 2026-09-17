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
from src.integrations.wildberries.endpoints import SETTLEMENT_REPORT_PATH
from src.integrations.wildberries.rate_limit import RateGate, statistics_rate_gate
from src.integrations.wildberries.schemas import WBReportDetailRow


class WBFinanceClient(BaseWBClient):
    """Client for the WB realization/finance report (``reportDetailByPeriod``)."""

    #: Rows asked for per request when the caller streams.
    #:
    #: WB's documented maximum, verified live 2026-09-14 on a 25 000-row ask
    #: that it answered in full. Affordable only because the body is parsed as
    #: it arrives: the walk that decoded whole pages was held to 10 000 rows by
    #: the worker's heap, and asking WB for its 100 000 anyway is what
    #: OOM-killed the 2026-08-11 harvest. On an endpoint serving ~4 requests an
    #: hour that limit is the schedule rather than an efficiency — NEVA's
    #: remaining backfill is 33 requests at 10 000 rows and 4 at 100 000.
    _STREAM_LIMIT = 100_000

    #: Rows handed over at a time by :meth:`stream_report_rows`, and therefore
    #: the real memory ceiling of a streamed walk: ~25 MB at 12.5 KB a row (a
    #: settlement row costs that much while the decoded dict and the
    #: :class:`WBReportDetailRow` coexist). Small enough that the request's row
    #: count stops mattering, large enough that the per-batch transaction
    #: overhead stays irrelevant beside a WB round trip.
    _STREAM_BATCH = 2_000

    #: Rows the freshness probe asks for. It only needs to know whether the
    #: window is empty, so one row is the whole answer.
    _PROBE_LIMIT = 1

    def __init__(
        self,
        settings: Settings,
        *,
        token: str,
        max_retries: int | None = None,
        rate_gate: RateGate | None = None,
    ) -> None:
        """Build the finance client against the Statistics surface.

        Args:
            settings: Transport configuration (base URL, timeouts, retries).
            token: The workspace's «Статистика»-scope bearer token.
            max_retries: Override for the retry ladder. The harvest lowers it
                because it pages **inside an open transaction** — see
                :mod:`src.modules.finreports.tasks.settlement`.
            rate_gate: Pacing gate override. The settlement walk passes a gate
                it has ALREADY taken this request's token from, outside the
                transaction; taking a second one here would double the wait for
                a budget of one request per fifteen minutes.
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
            # The ladder alone was never enough. A 429 here is a fifteen-minute
            # block, which no backoff this side of the transaction's own
            # timeout can wait out — the gate's job is that the second page is
            # not SENT until a token exists.
            rate_gate=rate_gate or statistics_rate_gate(settings, token=token),
            # And when one is answered anyway, the ladder must NOT honour the
            # wait WB names. The shared default tolerates a demanded wait up to
            # 900 s; on 2026-09-07 a 429 demanding 897 s was duly slept off
            # inside the harvest's open transaction, and PostgreSQL closed the
            # connection at 300 s idle — turning a source the harvest reports
            # as failed into a task that dies with an InterfaceError and takes
            # the other sources' rows with it. Anything past this is somebody
            # else's tick.
            retry_after_ceiling_seconds=45.0,
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
            SETTLEMENT_REPORT_PATH,
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

    @property
    def stream_limit(self) -> int:
        """Rows a streamed request asks WB for — the caller's short-page test."""
        return self._STREAM_LIMIT

    async def stream_report_rows(
        self,
        *,
        date_from: date,
        date_to: date,
        cursor: int = 0,
        reserve_seconds: float = 0.0,
    ) -> AsyncGenerator[list[WBReportDetailRow], None]:
        """Stream ONE request's settlement rows in batches, never holding a page.

        The endpoint's scarce resource is requests, not bytes: WB serves about
        four an hour per token and allows 100 000 rows in each. Decoding a whole
        page made the row count a memory problem instead, which is why the page
        size sat at 10 000 and a walk WB would serve in four requests took
        thirty-three. Parsing the body as it arrives moves the ceiling from the
        page to the batch, so the request count can drop by an order of
        magnitude without the heap noticing.

        One request, not a walk. The caller keeps the ``rrdid`` cursor and
        decides whether to ask again, because between pages is where it commits
        a transaction and re-reads its own coverage — and a generator owning
        that loop cannot express it.

        Args:
            date_from: Inclusive settlement-date window start.
            date_to: Inclusive settlement-date window end.
            cursor: ``rrdid`` to page from; 0 for the first page. Exclusive, so
                a row is returned exactly once across a walk.
            reserve_seconds: Non-zero marks this as background work that yields
                its window to anything a person is waiting on.

        Yields:
            Batches of at most :data:`_STREAM_BATCH` validated rows, in WB's own
            ``rrd_id`` order.

        Raises:
            IntegrationError: On a refused gate, an exhausted retry ladder, a
                malformed body, or an unexpected row shape.
        """
        async for raw in self._stream_json_items(
            "GET",
            SETTLEMENT_REPORT_PATH,
            params={
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "rrdid": cursor,
                "limit": self._STREAM_LIMIT,
            },
            batch_size=self._STREAM_BATCH,
            reserve_seconds=reserve_seconds,
        ):
            # Drained the same way a decoded page is: the raw dicts and the
            # models must not both exist for the whole batch.
            yield _validate_draining(raw)


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
