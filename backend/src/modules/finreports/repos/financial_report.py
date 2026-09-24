"""Data access for WB financial-report headers."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, text, update

from src.modules.finreports.constants import REFUND_DOC_TYPE
from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos.base import BaseRepository


@dataclass(frozen=True)
class LatestReportHeader:
    """The newest report on file: which one, what it covers, when we pulled it.

    A plain record rather than the ORM row — the P&L's freshness line is the
    only reader, it needs four scalars, and handing a detached model out of the
    repository would let a lazy attribute load on a closed session become a
    500 on a footnote.

    Attributes:
        report_id: WB ``realizationreport_id``.
        date_from / date_to: The period WB states the report covers. Either can
            be ``None`` — WB has served headers with no stated period.
        harvested_at: When the header was ingested (UTC).
    """

    report_id: int
    date_from: date | None
    date_to: date | None
    harvested_at: datetime


class FinancialReportRepository(BaseRepository):
    """Registry of harvested weekly WB realization reports."""

    model = FinancialReport

    async def latest_report(self, *, workspace_id: uuid.UUID) -> LatestReportHeader | None:
        """Return the newest report on file, or ``None`` for a fresh workspace.

        **Ordered by the settlement period, not by ingestion time.** A backfill
        pulls old reports long after the current one, so ``ORDER BY
        harvested_at`` would label a 2024 week as the newest thing WB published
        — on the one page whose job is to say how current the statement is.

        Headers with no stated period sort last (``NULLS LAST``): WB has served
        such headers, and they carry nothing the page could name. One is
        returned only when it is all this workspace has, and then the caller
        renders the period as unknown rather than inventing one.

        Args:
            workspace_id: Tenancy scope.

        Returns:
            The newest report's header, or ``None`` when none is harvested.
        """
        stmt = (
            select(
                FinancialReport.report_id,
                FinancialReport.date_from,
                FinancialReport.date_to,
                FinancialReport.harvested_at,
            )
            .where(FinancialReport.workspace_id == workspace_id)
            .order_by(
                FinancialReport.date_to.desc().nullslast(),
                FinancialReport.harvested_at.desc(),
            )
            .limit(1)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        return LatestReportHeader(
            report_id=row[0], date_from=row[1], date_to=row[2], harvested_at=row[3]
        )

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        """Return the last settlement day any harvested report covers.

        The harvest's freshness gate probes WB for the days after this one, so
        the figure has to be the end of the *stated* report period rather than
        ``max(rr_dt)``: a report routinely settles nothing on its last day, and
        probing from the last day that happens to carry a row would re-ask WB
        about days it has already published — a permanently "fresh" gate.

        Args:
            workspace_id: Tenancy scope.

        Returns:
            The greatest ``date_to`` on file, or ``None`` if this workspace has
            never been harvested.
        """
        stmt = select(func.max(FinancialReport.date_to)).where(
            FinancialReport.workspace_id == workspace_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def report_ids_since(self, *, workspace_id: uuid.UUID, since: date) -> set[int]:
        """Return the WB ``reportId`` of every report held whose period ends after ``since``.

        What the freshness gate compares WB's own report list against. Ids
        rather than dates because ids are what the Finance surface addresses a
        report by, and because an id cannot be ambiguous the way a period can:
        a report served out of order, a period WB splits at a month end, and a
        re-issued report are all just ids we do or do not hold.

        Args:
            workspace_id: Tenancy scope.
            since: Only reports whose period ends on or after this day.

        Returns:
            The ids, as a set — the caller reads membership only.
        """
        stmt = select(FinancialReport.report_id).where(
            FinancialReport.workspace_id == workspace_id,
            FinancialReport.date_to.isnot(None),
            FinancialReport.date_to >= since,
        )
        return set((await self._session.execute(stmt)).scalars())

    async def period_ends_since(self, *, workspace_id: uuid.UUID, since: date) -> list[date]:
        """Return the ``date_to`` of every report covering a period after ``since``.

        What the freshness gate compares WB's period arithmetic against: the
        set of periods we can prove we hold. ``latest_settled_date`` above is
        not a substitute — it is a maximum, and a maximum cannot see a hole
        behind it, which is exactly what a report WB serves out of order
        leaves. On 2026-09-07 the 01.09-06.09 report raised that maximum to
        06.09 while 31.08 was still unharvested, and the gate then asked only
        about days after 06.09 for ever.

        Bounded rather than the whole history: the gate only reasons about
        periods WB can still be about to serve, and reading 142 rows to answer
        a question about the last three is waste on a query that runs twenty-one
        times a day per workspace.

        Args:
            workspace_id: Tenancy scope.
            since: Only reports whose period ends on or after this day.

        Returns:
            The period ends, unordered — the caller reads membership only.
        """
        stmt = select(FinancialReport.date_to).where(
            FinancialReport.workspace_id == workspace_id,
            FinancialReport.date_to.isnot(None),
            FinancialReport.date_to >= since,
        )
        return [row for row in (await self._session.execute(stmt)).scalars() if row is not None]

    async def settlement_gap_days(
        self, *, workspace_id: uuid.UUID, since: date, through: date
    ) -> list[date]:
        """Days inside the harvested history that **no report period covers**.

        The detector for the failure that cost 31.08: WB serves a supplementary
        report late, the walk's window has already moved past the days it
        covers, and nothing ever asks again. The task succeeds, the counters
        move, and the P&L is quietly short a day.

        **Keyed on report PERIODS, not on rows.** "No settlement rows on day D"
        is not evidence of anything — a small seller genuinely has days with no
        sales, and Марат's whole 31.08 report was 45 rows. What is evidence is
        a day that falls inside the harvested range while belonging to no
        report we hold: WB's periods tile the calendar, so a hole in them is a
        report that is missing rather than a week that was quiet.

        A half-known period counts as the day it does know, matching
        :meth:`list_periods` — WB serves headers with one endpoint blank, and
        treating those as covering nothing would invent gaps around them.

        **The scan runs past the newest report, not up to it.** Bounding it by
        `max(date_to)` made the one hole that matters most invisible: a week WB
        has published and we have not harvested is not *between* two reports, it
        is after the last one, so every trailing day fell outside the range and
        the survey reported a sound history. That is what happened on
        2026-09-14 — three workspaces short the whole 07.09-13.09 week, gap
        count zero, no alert. ``through`` is what puts the trailing edge inside
        the range.

        A workspace holding **no report at all** still has no gaps. Never
        harvested is not the same as short a day, and with the scan reaching
        forward it is the one case where the two would otherwise become
        indistinguishable — a signup from this morning would report a fortnight
        of holes.

        Args:
            workspace_id: Tenancy scope.
            since: Ignore anything earlier. Bounds the scan and keeps the
                answer to gaps that are still actionable — WB does not serve
                arbitrarily old windows, so an ancient hole is a fact to record
                rather than an alert to raise.
            through: Last day a report can be *expected* for. Later days are
                not gaps, they are days WB has not published yet — see
                :data:`~src.modules.finreports.constants.SETTLEMENT_PUBLICATION_GRACE_DAYS`
                for how far behind today that has to sit to stay quiet while WB
                is merely slow.

        Returns:
            The uncovered days, oldest first; empty when the history is sound.
        """
        stmt = text("""
            WITH bounds AS (
                SELECT greatest(min(coalesce(date_from, date_to)), :since) AS lo,
                       CASE
                           WHEN max(coalesce(date_to, date_from)) IS NULL THEN NULL
                           ELSE greatest(max(coalesce(date_to, date_from)), :through)
                       END AS hi
                  FROM finreports.financial_report
                 WHERE workspace_id = :workspace_id
                   AND (date_from IS NOT NULL OR date_to IS NOT NULL)
            )
            SELECT day::date AS gap
              FROM bounds,
                   generate_series(bounds.lo, bounds.hi, interval '1 day') AS day
             WHERE NOT EXISTS (
                       SELECT 1
                         FROM finreports.financial_report r
                        WHERE r.workspace_id = :workspace_id
                          AND coalesce(r.date_from, r.date_to) <= day::date
                          AND coalesce(r.date_to, r.date_from) >= day::date
                   )
             ORDER BY gap
        """)
        rows = await self._session.execute(
            stmt, {"workspace_id": workspace_id, "since": since, "through": through}
        )
        return [row[0] for row in rows.all()]

    async def incomplete_report_ids(
        self, *, workspace_id: uuid.UUID, tolerance: float = 0.005
    ) -> set[int]:
        """Reports we hold a HEADER for and demonstrably not all the rows of.

        «Which reports do I hold» was answered by :meth:`report_ids_since` — the
        presence of a header — and that is only as true as the thing that writes
        headers. Until 2026-09-23 one was written with the first batch of rows,
        so a fetch that died half-way left a header over a fraction of a report
        and nothing ever asked again. Measured on NEVA 2026-09-24: 14 of 107
        reports short, one holding 13.8 % of its own money, and the seller's
        August showing nine days of nothing.

        The code no longer writes headers that way. Those rows do not repair
        themselves, though, because the id is present and a set difference sees
        only presence. So presence stops being the test: a report is held when
        our own arithmetic over its rows matches the ``forPaySum`` WB served for
        it, and both lanes subtract what this returns from their «held» set.

        The decomposition is WB's and the statement's alike — every row's
        ``ppvz_for_pay``, negated where :data:`REFUND_DOC_TYPE` says so — and it
        agrees to the kopeck on all 143 reports of «Демо»'s history. It used
        to count four named operations and drop the rest, which would have left
        a report carrying a damage compensation short for ever and re-fetched on
        every tick.

        Args:
            workspace_id: Tenancy scope.
            tolerance: Relative difference treated as agreement. Not zero, and
                the reason is termination rather than sloppiness: WB restates a
                settled week, and a report that could never match exactly would
                be re-fetched on every sweep for ever. Measured on NEVA the two
                populations separate cleanly — 20 reports inside 0.5 %, the
                worst genuine shortfall at 1.2 %.

        Returns:
            The ids to treat as NOT held. Empty for a workspace whose headers
            carry no WB totals yet, which is the honest answer: without the
            oracle there is no evidence either way, and guessing «incomplete»
            would re-fetch a whole history on no grounds.
        """
        stmt = text("""
            SELECT r.report_id
              FROM finreports.financial_report r
              LEFT JOIN finreports.logistics_transaction t
                     ON t.report_id = r.report_id
                    AND t.workspace_id = r.workspace_id
             WHERE r.workspace_id = :workspace_id
               AND r.wb_for_pay_sum IS NOT NULL
               AND r.wb_for_pay_sum <> 0
             GROUP BY r.report_id, r.wb_for_pay_sum
            HAVING abs(
                       r.wb_for_pay_sum - coalesce(sum(CASE
                           WHEN t.doc_type_name = :refund THEN -t.ppvz_for_pay
                           ELSE t.ppvz_for_pay END), 0)
                   ) > abs(r.wb_for_pay_sum) * :tolerance
        """)
        rows = await self._session.execute(
            stmt,
            {
                "workspace_id": workspace_id,
                "tolerance": tolerance,
                "refund": REFUND_DOC_TYPE,
            },
        )
        return {int(row[0]) for row in rows.all()}

    async def refresh_wb_totals(
        self, *, workspace_id: uuid.UUID, totals: Sequence[tuple[int, Decimal, Decimal, Decimal]]
    ) -> int:
        """Record WB's own per-report sums on reports this workspace ALREADY holds.

        An UPDATE and deliberately never an upsert, because the difference is
        load-bearing rather than stylistic. This table's row set is the answer
        to «which reports do I hold» (:meth:`report_ids_since`), so inserting a
        header for a report whose rows have not been fetched would mark it held
        and the walk would never fetch it. An UPDATE that matches nothing is the
        correct outcome for a report WB has listed and we have not taken.

        Called with whatever WB's list named this tick, held or not, which is
        why the safety has to live here rather than in each caller's filter.

        Nothing is committed; the caller owns the transaction.

        Args:
            workspace_id: Tenancy scope — part of the match, not a filter added
                afterwards, so one tenant's list can never touch another's rows.
            totals: ``(report_id, for_pay, retail_amount, bank_payment)`` per
                report, as ``sales-reports/list`` served them.

        Returns:
            How many held reports were updated.
        """
        if not totals:
            return 0
        updated = 0
        for report_id, for_pay, retail_amount, bank_payment in totals:
            result = cast(
                CursorResult[Any],
                await self._session.execute(
                    update(FinancialReport)
                    .where(
                        FinancialReport.report_id == report_id,
                        FinancialReport.workspace_id == workspace_id,
                    )
                    .values(
                        wb_for_pay_sum=for_pay,
                        wb_retail_amount_sum=retail_amount,
                        wb_bank_payment_sum=bank_payment,
                    )
                ),
            )
            updated += result.rowcount or 0
        return updated

    async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
        """Return each harvested report's ``(report_id, date_from, date_to)``.

        can be scoped to, and the list the SPA's period picker is built from.

        **A half-known period is served, not dropped.** WB leaves the stated
        period blank on the occasional row, and the header takes
        ``stated_from or rr_dt`` per side (see ``ingestion/rows.py``), so a
        report can land with one endpoint known and the other NULL. Requiring
        ``date_from`` here meant such a report was counted by
        :meth:`latest_settled_date` — ``max(date_to)``, which filters nothing —
        and served by neither: «Обновить» announced a settlement day the picker
        could not reach, and the freshness gate, probing the days *after* that
        day, never asked for the report again. Coalescing the two sides makes
        the divergence unrepresentable: every report ``max(date_to)`` can see
        has a ``date_to``, and therefore appears here. A report with only one
        endpoint reads as a one-day week, which is wrong about the week and
        right about the report existing — and no settlement figure is derived
        from this period, only the picker's bounds (the P&L aggregates
        ``rr_dt``).

        Args:
            workspace_id: Tenancy scope.

        Returns:
            One tuple per report with at least one known endpoint, newest first.
        """
        start = func.coalesce(FinancialReport.date_from, FinancialReport.date_to)
        end = func.coalesce(FinancialReport.date_to, FinancialReport.date_from)
        stmt = (
            select(FinancialReport.report_id, start, end)
            .where(
                FinancialReport.workspace_id == workspace_id,
                or_(
                    FinancialReport.date_from.isnot(None),
                    FinancialReport.date_to.isnot(None),
                ),
            )
            .order_by(start.desc())
        )
        return [(r[0], r[1], r[2]) for r in (await self._session.execute(stmt)).all()]
