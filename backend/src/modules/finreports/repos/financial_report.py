"""Data access for WB financial-report headers."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos.base import BaseRepository


class FinancialReportRepository(BaseRepository):
    """Registry of harvested weekly WB realization reports."""

    model = FinancialReport

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
