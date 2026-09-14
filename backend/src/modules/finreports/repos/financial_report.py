"""Data access for WB financial-report headers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, or_, select, text

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
