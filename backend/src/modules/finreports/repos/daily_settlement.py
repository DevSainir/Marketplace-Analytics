"""Data access for the provisional daily settlement tail.

Two jobs: remember which daily reports a workspace holds, so the lane does not
re-fetch them at one request a minute, and fingerprint their rows, so a re-read a
day later can say whether WB changed its mind. The reasoning for keeping this
apart from ``financial_report`` is in
:mod:`src.modules.finreports.models.daily_settlement_report`.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple
from typing import cast as typed

from sqlalchemy import CursorResult, Text, cast, delete, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import aggregate_order_by, insert

from src.modules.finreports.models import (
    DailyReportVerdict,
    DailySettlementReport,
    LogisticsTransaction,
)
from src.modules.finreports.repos.base import BaseRepository

_T = LogisticsTransaction

#: The columns a restatement would have to change to matter, in a fixed order.
#:
#: Everything the P&L reads a figure from, plus the four fields that say which
#: operation a figure belongs to. Not every column in the table: `report_id`
#: moves on its own when the weekly lane later re-owns a row, and `harvested_at`
#: moves on every write, so either would report a change that is not one.
_FINGERPRINTED = (
    _T.rrd_id,
    _T.rr_dt,
    _T.nm_id,
    _T.supplier_oper_name,
    _T.doc_type_name,
    _T.quantity,
    _T.retail_amount,
    _T.retail_price_withdisc_rub,
    _T.ppvz_for_pay,
    _T.delivery_rub,
    _T.penalty,
    _T.additional_payment,
    _T.storage_fee,
    _T.acceptance,
    _T.deduction,
    _T.acquiring_fee,
    _T.ppvz_sales_commission,
)


class Fingerprint(NamedTuple):
    """What a daily report's rows looked like at one moment.

    Attributes:
        rows: How many rows the report has in ``logistics_transaction``.
        digest: MD5 over :data:`_FINGERPRINTED`, every row, in ``rrd_id`` order.
            Both halves are kept because only the pair is readable in a log line:
            «763 → 765» names the change, the digest only proves it.

    A day WB settled nothing on fingerprints as ``(0, "")`` and will compare
    equal to itself a day later. That verdict is true and vacuous, and ``rows``
    is what says so: a recorded «unchanged» over 0 rows is not evidence that a
    daily report is stable.
    """

    rows: int
    digest: str


class ListedTotals(NamedTuple):
    """WB's own totals for one report, as ``sales-reports/list`` serves them.

    The day-later screen compares these against the same three fields listed
    again — WB's figure against WB's earlier figure. Deliberately not against
    anything we compute: our reconstruction of ``forPaySum`` was 128.26 KGS out
    on report 989286628 until the sign was found to live in the document type
    (:data:`~src.modules.finreports.constants.REFUND_DOC_TYPE`), and the
    next such mistake would make a screen built on our own arithmetic fire on a
    difference that is ours and miss the one that is WB's.
    """

    for_pay: Decimal | None
    retail_amount: Decimal | None
    bank_payment: Decimal | None

    def known(self) -> bool:
        """Whether WB stated anything at all — nothing is not agreement."""
        return self.for_pay is not None


class PendingVerification(NamedTuple):
    """A daily report whose day-later re-read is due.

    Attributes:
        report_id: WB's own id, the unit the re-read fetches.
        day: The settlement day it covers — compared against the weekly
            frontier to decide whether re-reading it is still meaningful.
        rows / digest: What the first ingest recorded, to compare against.
        totals: WB's own totals at ingest, or all-``None`` for a report booked
            before they were kept. The screen cannot conclude «unchanged» from
            absent totals, so such a report falls through to a detail re-read.
    """

    report_id: int
    day: date
    rows: int
    digest: str
    totals: ListedTotals


class DailySettlementRepository(BaseRepository):
    """The daily tail's own bookkeeping, and the fingerprints it rests on."""

    model = DailySettlementReport

    async def fingerprint(self, *, workspace_id: uuid.UUID, report_id: int) -> Fingerprint:
        """Fingerprint one daily report's rows, as they stand in the detail.

        Computed in PostgreSQL over the rows themselves rather than over what WB
        sent, so the figure recorded at ingest and the figure recorded a day
        later are produced by the same expression. Two sums that agree because
        both were computed wrong the same way would at least be comparable; two
        computed differently would not.

        Args:
            workspace_id: Tenancy scope.
            report_id: WB's daily ``reportId``.

        Returns:
            A :class:`Fingerprint`. Zero rows and an empty digest when the report
            has none — see the class, which says why that comparison is vacuous.
        """
        parts = [func.coalesce(cast(column, Text), "") for column in _FINGERPRINTED]
        stmt = select(
            func.count(),
            func.coalesce(
                func.md5(
                    func.string_agg(
                        func.concat_ws("|", *parts),
                        aggregate_order_by(literal_column("','"), _T.rrd_id),
                    )
                ),
                "",
            ),
        ).where(_T.workspace_id == workspace_id, _T.report_id == report_id)
        rows, digest = (await self._session.execute(stmt)).one()
        return Fingerprint(rows=int(rows or 0), digest=str(digest or ""))

    async def held_ids(self, *, workspace_id: uuid.UUID, since: date) -> set[int]:
        """Return the daily ``reportId`` held for days on or after ``since``.

        What the lane compares WB's list against. Ids rather than days, for the
        same reason the weekly gate uses ids: a report re-issued for a day
        already held is a new id and must be fetched again.

        Args:
            workspace_id: Tenancy scope.
            since: Earliest settlement day to consider.

        Returns:
            The ids, as a set — membership is all the caller reads.
        """
        stmt = select(DailySettlementReport.report_id).where(
            DailySettlementReport.workspace_id == workspace_id,
            DailySettlementReport.day >= since,
        )
        return set((await self._session.execute(stmt)).scalars())

    async def covered_through(self, *, workspace_id: uuid.UUID) -> date | None:
        """Return the newest day the provisional tail covers, if any.

        The P&L's freshness line reads this to say «плюс предварительно по 22
        сен» ("plus provisional to 22 Sep") beside the settled weekly period. It
        is deliberately NOT mixed into `latest_settled`: one of the two claims is
        a WB settlement document and the other is a day we have not yet proved
        stable.

        Args:
            workspace_id: Tenancy scope.

        Returns:
            The greatest ``day`` on file, or ``None`` when the tail is empty.
        """
        stmt = select(func.max(DailySettlementReport.day)).where(
            DailySettlementReport.workspace_id == workspace_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def record_ingest(
        self,
        *,
        workspace_id: uuid.UUID,
        report_id: int,
        day: date,
        create_dt: date | None,
        fingerprint: Fingerprint,
        totals: ListedTotals,
    ) -> None:
        """Record a freshly harvested daily report and what its rows looked like.

        Re-harvesting the same id (the lane retrying a report that stopped
        early) refreshes the fingerprint and **clears the verification**: the
        stored digest must always describe the rows as first completely
        ingested, or a day-later comparison would be against a half-written
        report and report a change that is only our own retry.

        Args:
            workspace_id: Tenancy scope.
            report_id: WB's daily ``reportId``.
            day: The settlement day it covers.
            create_dt: WB's own ``createDate``.
            fingerprint: The rows as they now stand.
            totals: WB's own totals for the report, from the same list call that
                discovered it. What the day-later screen compares against.
        """
        stmt = (
            insert(DailySettlementReport)
            .values(
                report_id=report_id,
                workspace_id=workspace_id,
                day=day,
                create_dt=create_dt,
                rows=fingerprint.rows,
                digest=fingerprint.digest,
                first_seen_at=func.now(),
                wb_for_pay_sum=totals.for_pay,
                wb_retail_amount_sum=totals.retail_amount,
                wb_bank_payment_sum=totals.bank_payment,
            )
            .on_conflict_do_update(
                index_elements=[DailySettlementReport.report_id],
                set_={
                    "workspace_id": workspace_id,
                    "day": day,
                    "create_dt": create_dt,
                    "rows": fingerprint.rows,
                    "digest": fingerprint.digest,
                    "first_seen_at": func.now(),
                    "verified_at": None,
                    "verified_rows": None,
                    "verified_digest": None,
                    "verdict": None,
                    "wb_for_pay_sum": totals.for_pay,
                    "wb_retail_amount_sum": totals.retail_amount,
                    "wb_bank_payment_sum": totals.bank_payment,
                },
            )
        )
        await self._session.execute(stmt)

    async def due_for_verification(
        self, *, workspace_id: uuid.UUID, after_hours: int, limit: int, now: datetime | None = None
    ) -> Sequence[PendingVerification]:
        """Return the daily reports whose re-read is due, oldest first.

        Args:
            workspace_id: Tenancy scope.
            after_hours: How long a report must have been held before it is
                worth re-reading. The question is whether a day-old report
                changes, so anything shorter answers a different one.
            limit: Most reports to return. The re-read costs one WB request a
                minute, so the batch is bounded rather than «all of them».
            now: Reference time, injected for tests.

        Returns:
            The pending reports, oldest first — a queue, so a backlog drains in
            the order the reports were harvested.
        """
        cutoff = (now or datetime.now(UTC)) - timedelta(hours=after_hours)
        stmt = (
            select(
                DailySettlementReport.report_id,
                DailySettlementReport.day,
                DailySettlementReport.rows,
                DailySettlementReport.digest,
                DailySettlementReport.wb_for_pay_sum,
                DailySettlementReport.wb_retail_amount_sum,
                DailySettlementReport.wb_bank_payment_sum,
            )
            .where(
                DailySettlementReport.workspace_id == workspace_id,
                DailySettlementReport.verdict.is_(None),
                DailySettlementReport.first_seen_at <= cutoff,
            )
            .order_by(DailySettlementReport.day)
            .limit(limit)
        )
        return [
            PendingVerification(
                report_id=row[0],
                day=row[1],
                rows=row[2],
                digest=row[3],
                totals=ListedTotals(for_pay=row[4], retail_amount=row[5], bank_payment=row[6]),
            )
            for row in (await self._session.execute(stmt)).all()
        ]

    async def record_verification(
        self,
        *,
        workspace_id: uuid.UUID,
        report_id: int,
        verdict: DailyReportVerdict,
        found: Fingerprint | None = None,
    ) -> None:
        """Record what the day-later re-read found.

        Scoped by workspace as well as by id. The id alone is unique, but the
        worker connects as the table owner, so row-level security does not
        stand behind this statement — the ``WHERE`` is the only tenancy check.

        Args:
            workspace_id: Owning workspace.
            report_id: WB's daily ``reportId``.
            verdict: What the comparison concluded.
            found: The fingerprint the re-read produced, or ``None`` for
                :attr:`DailyReportVerdict.SUPERSEDED`, where nothing was
                fetched and inventing a figure would be worse than leaving the
                columns empty.
        """
        values: dict[str, object] = {
            "verified_at": func.now(),
            "verdict": verdict.value,
            "verified_rows": found.rows if found else None,
            "verified_digest": found.digest if found else None,
        }
        await self._session.execute(
            update(DailySettlementReport)
            .where(
                DailySettlementReport.workspace_id == workspace_id,
                DailySettlementReport.report_id == report_id,
            )
            .values(**values)
        )

    async def drop_rows(self, *, workspace_id: uuid.UUID, report_ids: Sequence[int]) -> int:
        """Delete the settlement rows still filed under these daily reports.

        Only rows that still carry the DAILY ``report_id``: a row the weekly
        report has since rewritten carries the weekly id and is untouched. The
        rollup needs no help — a day that lost rows fails its row count and is
        rebuilt on the next read.

        Args:
            workspace_id: Tenancy scope.
            report_ids: The daily ``reportId`` whose rows go.

        Returns:
            How many rows were deleted.
        """
        if not report_ids:
            return 0
        result = typed(
            CursorResult[Any],
            await self._session.execute(
                delete(LogisticsTransaction).where(
                    LogisticsTransaction.workspace_id == workspace_id,
                    LogisticsTransaction.report_id.in_(list(report_ids)),
                )
            ),
        )
        return int(result.rowcount or 0)

    async def drop_closed_days(self, *, workspace_id: uuid.UUID, through: date, since: date) -> int:
        """Delete daily-report rows for days the weekly report has closed.

        A provisional row lives only until its day is settled. The weekly report
        rewrites every row it shares with the daily one under its own id, so
        whatever still carries a daily id on a closed day is a row WB did not put
        in the weekly settlement — and the weekly settlement is the document.

        Args:
            workspace_id: Tenancy scope.
            through: The settled frontier; days on or before it are closed.
            since: The oldest day worth sweeping. Bounds the join: rows of older
                daily reports were swept on the tick their day closed.

        Returns:
            How many rows were deleted.
        """
        report = DailySettlementReport
        closed = select(report.report_id).where(
            report.workspace_id == workspace_id,
            report.day <= through,
            report.day >= since,
        )
        result = typed(
            CursorResult[Any],
            await self._session.execute(
                delete(LogisticsTransaction).where(
                    LogisticsTransaction.workspace_id == workspace_id,
                    LogisticsTransaction.report_id.in_(closed),
                )
            ),
        )
        return int(result.rowcount or 0)

    async def forget(self, *, workspace_id: uuid.UUID, report_id: int) -> None:
        """Drop a daily report's record, so the tail fetches it again as new.

        Used when a re-read deleted the report's rows and then could not finish:
        without the record the report reads as missing, and the next tick —
        a quarter of an hour, not a day — puts its rows back.
        """
        await self._session.execute(
            delete(DailySettlementReport).where(
                DailySettlementReport.workspace_id == workspace_id,
                DailySettlementReport.report_id == report_id,
            )
        )
