"""Write-side ingestion for ``finreports`` — flatten WB payloads into the schema.

Pure persistence (mirrors monitoring's ingestion): each method maps a list of
typed WB rows onto DB dicts and idempotently upserts them. The client-calling
orchestration (building per-workspace clients, fetching) lives in the tasks
layer, so this service stays session-bound and unit-testable.

The mapping itself lives in :mod:`.rows` and the upsert column lists in
:mod:`.columns`; what is left here is the repository choreography.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Sequence
from contextlib import aclosing

from src.integrations.wildberries.schemas import WBFinanceReportHeader, WBReportDetailRow
from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
    SettlementUploadRepository,
)
from src.modules.finreports.services.ingestion.columns import REPORT_UPDATE, TXN_UPDATE
from src.modules.finreports.services.ingestion.rows import dedupe, settlement_row
from src.modules.finreports.services.settlement_upload.reconcile import settle_upload_on_booking


class IngestionService:
    """Persists harvested WB finance-report rows and report headers."""

    def __init__(
        self,
        *,
        transaction_repo: LogisticsTransactionRepository,
        report_repo: FinancialReportRepository,
        upload_repo: SettlementUploadRepository | None = None,
    ) -> None:
        """Wire the ingestion service from the finreports repositories.

        ``upload_repo`` lets a booked header retire the hand-uploaded file that
        stood in for its report — see :mod:`..settlement_upload.reconcile`.
        """
        self._transactions = transaction_repo
        self._reports = report_repo
        self._uploads = upload_repo

    async def record_report_header(
        self, header: WBFinanceReportHeader, *, workspace_id: uuid.UUID
    ) -> bool:
        """Write one weekly report's header from WB's OWN list entry.

        Headers used to be derived from the rows, and that was wrong in two
        ways that only showed under scrutiny.

        **It wrote the header too early.** The rows commit in batches, so the
        header landed with the first batch — and a fetch that died after it left
        a header for a report whose rows were mostly absent. Nothing afterwards
        could tell: «which reports do I hold» is a set of ids taken from this
        table, so the half-fetched report counted as held and was never asked
        for again. Written here instead, once the walk has the whole report, the
        table means what its readers think it means.

        **It could not carry WB's own totals.** ``retailAmountSum``,
        ``forPaySum`` and ``bankPaymentSum`` are on the list entry and on no
        row, so a header built from rows had to leave them empty — which is
        what every header on «Демо» still had on 2026-09-23. They are the
        one figure the P&L can be checked against that does not come from our
        own arithmetic, and ``docs/finreports/PNL.md`` is explicit that most
        ways to get a settlement figure wrong produce a plausible statement
        rather than an error.

        **Nor is a header written over no rows when WB says there is money in
        the report.** WB lists a report before it serves its rows — 983241109
        was served eight days late — and an empty answer then reads as «the
        report ended». Booked, the id would count as held with nothing behind
        it; refused, it stays missing and is asked for again. A report whose
        every WB total is zero may be booked empty, since nothing is owed.

        Nothing is committed here; the caller owns the transaction.

        Args:
            header: WB's list entry for this report.
            workspace_id: Owning workspace.

        Returns:
            Whether the header was written.
        """
        owes_something = any(
            (
                header.for_pay_sum,
                header.retail_amount_sum,
                header.delivery_service_sum,
                header.paid_storage_sum,
                header.paid_acceptance_sum,
                header.deduction_sum,
                header.penalty_sum,
                header.additional_payment_sum,
                header.bank_payment_sum,
            )
        )
        if owes_something and not await self._transactions.holds_report(
            workspace_id=workspace_id, report_id=header.report_id
        ):
            return False
        await self._reports.bulk_upsert(
            [
                {
                    "report_id": header.report_id,
                    "workspace_id": workspace_id,
                    "date_from": header.date_from,
                    "date_to": header.date_to,
                    "currency": header.currency,
                    "create_dt": header.create_date,
                    "wb_for_pay_sum": header.for_pay_sum,
                    "wb_retail_amount_sum": header.retail_amount_sum,
                    "wb_bank_payment_sum": header.bank_payment_sum,
                }
            ],
            conflict_columns=["report_id"],
            update_columns=REPORT_UPDATE,
        )
        if self._uploads is not None:
            await settle_upload_on_booking(
                self._uploads, workspace_id=workspace_id, report_id=header.report_id
            )
        return True

    async def ingest_settlement_rows(
        self,
        pages: AsyncGenerator[Sequence[WBReportDetailRow], None],
        *,
        workspace_id: uuid.UUID,
    ) -> int:
        """Upsert settlement rows **without** writing report headers.

        The single row path since 2026-09-24, when ``ingest_finance_report`` —
        which wrote headers derived from the rows — was deleted with the script
        that was its last caller. Both lanes ingest with this: the weekly walk
        books its header separately, from WB's list entry and only after all
        the rows (:meth:`record_report_header`), and the provisional daily lane
        books none. The rows are the same rows — a daily report and the weekly
        report covering it share their ``rrdId`` one for one — so they belong in
        ``logistics_transaction`` like any other, and the P&L picks them up by
        ``rr_dt`` with nothing else to change.

        For the daily lane, headers are what must not be written. ``financial_report`` is where
        the weekly machinery reads «how far is this workspace settled» from, as
        ``max(date_to)``; a daily header for yesterday would answer that
        question with yesterday and the freshness gate would stop asking for the
        weekly report altogether. The daily lane keeps its own bookkeeping
        instead — see
        :class:`~src.modules.finreports.models.daily_settlement_report.DailySettlementReport`.

        Args:
            pages: The paginated walk. Consumed and closed here.
            workspace_id: Owning workspace.

        Returns:
            The number of settlement rows upserted.
        """
        total = 0
        async with aclosing(pages):
            async for page in pages:
                total += await self._upsert_settlement_rows(page, workspace_id=workspace_id)
        return total

    async def _upsert_settlement_rows(
        self, page: Sequence[WBReportDetailRow], *, workspace_id: uuid.UUID
    ) -> int:
        """Upsert one page of settlement rows by ``rrd_id``.

        Shared by both ingests above so the two lanes cannot drift into writing
        the same rows differently — which, since they ARE the same rows, would
        show up as a P&L that changes when a day is re-harvested from the other
        lane.
        """
        return await self._transactions.bulk_upsert(
            # WB's cursor is exclusive, so a repeat inside one page is the only
            # way a duplicate key can reach the statement — and ON CONFLICT DO
            # UPDATE rejects the whole batch if one does.
            dedupe(
                [settlement_row(row, workspace_id=workspace_id) for row in page],
                keys=["rrd_id"],
            ),
            conflict_columns=["rrd_id"],
            update_columns=TXN_UPDATE,
        )
