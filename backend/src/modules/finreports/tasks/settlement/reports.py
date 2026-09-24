"""Walking WB's settlement history one REPORT at a time.

The unit WB itself publishes in. `POST /sales-reports/detailed/{reportId}`
serves one report whole, so a report is either fully ingested or it is not —
there is no «window half-covering a report» state to carry, which is most of
what the endpoint this replaced made the walk keep track of.

The forward harvest always walks this way: it is fetching the report WB
published this morning, one id at a time, and the atomicity is worth more than
the requests. The history backfill walks this way only for a single stray
report — see :mod:`~src.modules.finreports.tasks.settlement.window` for what it
does with a run of them.

**The walk certifies only its unbroken prefix.** A later report succeeding must
never certify a gap in front of it.

**Booking is the last step, and it is checked.** A completed report's header is
written from WB's list entry in a transaction of its own, after its rows, and is
refused when WB lists money in the report and none of its rows are held. Once
booked, the report's signed payout is compared with WB's ``forPaySum``
(:func:`~src.modules.finreports.tasks.settlement.reconcile.reconcile_against_wb`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import NamedTuple

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.endpoints import SALES_REPORTS_DETAILED_PATH
from src.integrations.wildberries.rate_limit import RateGate, finance_reports_rate_gate
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.services import IngestionService
from src.modules.finreports.tasks.settlement.page import _ingest_one_streamed_page
from src.modules.finreports.tasks.settlement.reconcile import reconcile_against_wb
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


class SettlementWalk(NamedTuple):
    """What one workspace's settlement walk achieved.

    Attributes:
        rows: Settlement rows ingested across every report.
        windows_failed: Reports that stopped early — WB withheld a page, or the
            walk ran out of rate budget part-way. Still named for windows
            because it is what the harvest reports as a failed source and the
            alert joins on that name.
        completed_through: ``date_to`` of the last report in the **unbroken
            prefix** of completed ones, or ``None`` when the first stopped
            early. A high-water date cannot describe a gap, so it must never
            be handed out with one behind it.
    """

    rows: int
    windows_failed: int
    completed_through: date | None


class MissingReport(NamedTuple):
    """A report WB has formed that this workspace does not hold.

    Attributes:
        report_id: WB's own ``reportId`` — the walk's unit of work.
        date_to: Last settlement day the report covers, which is what moves
            the watermark once the report is complete.
        header: WB's own ``sales-reports/list`` entry, when the caller has one.
            Written to ``financial_report`` **after** the report is fully
            ingested, and only then — see
            :meth:`~src.modules.finreports.services.ingestion.service.IngestionService.record_report_header`
            for why deriving it from the rows was wrong in two directions.

            ``None`` says «this walk books no weekly header», which is what the
            provisional daily lane needs: a daily header in ``financial_report``
            would answer «how far is this workspace settled» with yesterday and
            the freshness gate would stop asking for the weekly report at all.
            That used to be expressed by passing a different ingest function;
            it is now a property of the work item, so a caller cannot get the
            rows right and the header wrong.
        date_from: First settlement day the report covers, when known. The
            the reports' whole span, and ``date_to`` alone is one day of it.
    """

    report_id: int
    date_to: date
    header: WBFinanceReportHeader | None = None
    date_from: date | None = None


async def walk_settlement_reports(
    *,
    tokens: WorkspaceTokenBundle,
    reports: Sequence[MissingReport],
    build_ingestion: object,
) -> SettlementWalk:
    """Fetch every report this workspace is missing, one request per page.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The reports to fetch, **oldest first**. The order is what the
            prefix rule below means; a caller that shuffles them would
            certify a gap.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService` — injected rather than imported so this
            module does not reach back into the harvest that calls it.

    Returns:
        A :class:`SettlementWalk`. ``completed_through`` stops at the **first**
        report that did not finish, so a later one that happened to succeed
        can never certify the ones before it.
    """
    if not tokens.finance:
        return SettlementWalk(0, 0, None)

    gate = finance_reports_rate_gate(settings, token=tokens.finance)
    rows = 0
    failed = 0
    completed_through: date | None = None
    prefix_intact = True
    for report in reports:
        report_rows, complete = await _harvest_report(
            tokens=tokens,
            report=report,
            gate=gate,
            build_ingestion=build_ingestion,
        )
        rows += report_rows
        if complete:
            if prefix_intact:
                completed_through = report.date_to
        else:
            failed += 1
            prefix_intact = False
    if failed:
        logger.error(
            "finreports: settlement incomplete for %s — %d of %d report(s) stopped early; "
            "the P&L is short those days until a later tick asks again.",
            tokens.name,
            failed,
            len(reports),
        )
    return SettlementWalk(rows, failed, completed_through)


async def _harvest_report(
    *,
    tokens: WorkspaceTokenBundle,
    report: MissingReport,
    gate: RateGate,
    build_ingestion: object,
) -> tuple[int, bool]:
    """Harvest one report, a page per request, and say whether it finished.

    Args:
        tokens: The workspace's decrypted WB credentials.
        report: The report to fetch.
        gate: The walk's rate gate. A token is taken per PAGE, and always
            before the page's session is opened.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService`.

    Returns:
        ``(rows, complete)``. ``complete`` is False when WB withheld a page or
        the walk ran out of rate budget part-way — the rows already committed
        stay committed, and the remainder falls to a later tick.
    """
    rows = 0
    cursor = 0
    while True:
        try:
            # Outside the session, and this is the whole point: the wait for
            # WB's next token is a minute long, and PostgreSQL closes a
            # transaction left idle for 300 s.
            await gate.acquire(SALES_REPORTS_DETAILED_PATH)
        except IntegrationError as exc:
            logger.warning(
                "finreports: settlement report %d for %s stopped — no rate token: %s",
                report.report_id,
                tokens.name,
                exc,
            )
            return rows, False
        page = await _ingest_one_streamed_page(
            tokens=tokens,
            report_id=report.report_id,
            cursor=cursor,
            build_ingestion=build_ingestion,
            gate=gate,
        )
        # Added before the check, never inside it: a request that died mid-body
        # has already committed whatever batches reached the database, and those
        # rows are as real as any other.
        rows += page.rows
        if not page.ok:
            return rows, False
        if page.next_cursor is None:
            # The header goes in HERE and nowhere earlier. It is the marker that
            # says «this report is held», and writing it while the rows were
            # still arriving is what made a fetch that died half-way
            # indistinguishable from one that finished — the id counted as held
            # and nothing ever asked for the rest.
            booked = await _book_report(
                report=report, tokens=tokens, build_ingestion=build_ingestion
            )
            logger.info(
                "finreports: settlement report %d (through %s) ingested %d rows for %s.",
                report.report_id,
                report.date_to,
                rows,
                tokens.name,
            )
            return rows, booked
        cursor = page.next_cursor


async def _book_report(
    *,
    report: MissingReport,
    tokens: WorkspaceTokenBundle,
    build_ingestion: object,
) -> bool:
    """Record a completed report's header, in a transaction of its own.

    After the rows and never before, which is the whole point: the header is
    what ``report_ids_since`` reads to answer «which reports do I hold», so it
    has to mean «all of it», not «some of it started arriving».

    A walk carrying no header books nothing — that is the provisional daily
    lane, whose reports must not reach ``financial_report`` at all.

    Failing here is safe and self-correcting. The rows are committed and
    upserted by ``rrd_id``; the report simply stays on the missing list and is
    fetched again, writing the same rows and then the header.

    Then the booked report is checked against WB's own ``forPaySum``. At this
    moment the rows and the total come from the same fetch, so any gap is ours
    — a report cut short, or an operation signed the wrong way — and it lands
    in ``settlement_payout_divergence``, which the alert reads. Best effort: a
    failed measurement must not undo a booking that succeeded.

    Returns:
        Whether the report is now held. ``False`` when WB listed money in it and
        served no rows — see
        :meth:`~src.modules.finreports.services.ingestion.service.IngestionService.record_report_header`
        — and ``True`` for a headerless walk, which has nothing to book.

    Args:
        report: The report just completed, with WB's own list entry on it.
        tokens: The workspace whose report it is.
        build_ingestion: Factory taking a session and returning an
            :class:`IngestionService`.
    """
    if report.header is None:
        return True
    async with AsyncSessionLocal() as session:
        ingestion: IngestionService = build_ingestion(session)  # type: ignore[operator]
        booked = await ingestion.record_report_header(
            report.header, workspace_id=tokens.workspace_id
        )
        await session.commit()
        if not booked:
            logger.warning(
                "finreports: report %d for %s served no rows although WB lists money in "
                "it; left missing to be asked for again.",
                report.report_id,
                tokens.name,
            )
            return False
        try:
            await reconcile_against_wb(
                session, header=report.header, workspace_id=tokens.workspace_id, name=tokens.name
            )
        except Exception:
            logger.warning(
                "finreports: could not check report %d against WB's total for %s.",
                report.report_id,
                tokens.name,
                exc_info=True,
            )
    return True


__all__ = ["MissingReport", "SettlementWalk", "walk_settlement_reports"]
