"""Data access for WB financial-report headers."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, or_, select

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos.base import BaseRepository


class FinancialReportRepository(BaseRepository):
    """Registry of harvested weekly WB realization reports."""

    model = FinancialReport

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
