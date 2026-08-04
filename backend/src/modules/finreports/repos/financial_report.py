"""Data access for WB financial-report headers."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select

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

        can be scoped to.

        Args:
            workspace_id: Tenancy scope.

        Returns:
            One tuple per report with a resolved period, newest first.
        """
        stmt = (
            select(
                FinancialReport.report_id,
                FinancialReport.date_from,
                FinancialReport.date_to,
            )
            .where(
                FinancialReport.workspace_id == workspace_id,
                FinancialReport.date_from.isnot(None),
            )
            .order_by(FinancialReport.date_from.desc())
        )
        return [(r[0], r[1], r[2]) for r in (await self._session.execute(stmt)).all()]
