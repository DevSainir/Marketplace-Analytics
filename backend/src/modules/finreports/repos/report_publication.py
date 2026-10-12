"""Write side of the publication log — see :mod:`..models.report_publication`."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.models import ReportPublication
from src.modules.finreports.repos.base import BaseRepository


class ReportPublicationRepository(BaseRepository):
    """When ``sales-reports/list`` first named each report."""

    model = ReportPublication

    async def record_first_listings(
        self,
        *,
        workspace_id: uuid.UUID,
        period: str,
        headers: Sequence[WBFinanceReportHeader],
        listed_at: datetime,
        prior_list_at: datetime | None,
    ) -> list[int]:
        """Write each report this log has not seen before; leave the rest alone.

        ``ON CONFLICT DO NOTHING``, never an update: the first sighting is the
        fact being kept, and every later tick names the same report again.

        Args:
            workspace_id: Tenancy scope.
            period: ``weekly`` or ``daily`` — which list answered.
            headers: The reports to consider, as WB listed them.
            listed_at: When this list answer arrived.
            prior_list_at: When the previous answer for this workspace and
                period arrived, or ``None`` when none is on record.

        Returns:
            The ids written by this call — the reports first seen now.
        """
        if not headers:
            return []
        stmt = (
            insert(ReportPublication)
            .values(
                [
                    {
                        "report_id": header.report_id,
                        "workspace_id": workspace_id,
                        "period": period,
                        "date_from": header.date_from,
                        "date_to": header.date_to,
                        "create_date": header.create_date,
                        "first_listed_at": listed_at,
                        "prior_list_at": prior_list_at,
                    }
                    for header in headers
                ]
            )
            .on_conflict_do_nothing(index_elements=["report_id"])
            .returning(ReportPublication.report_id)
        )
        return list((await self._session.execute(stmt)).scalars())

    async def list_for(self, *, workspace_id: uuid.UUID) -> list[ReportPublication]:
        """Every logged report for one workspace, newest period first."""
        stmt = (
            select(ReportPublication)
            .where(ReportPublication.workspace_id == workspace_id)
            .order_by(ReportPublication.date_to.desc(), ReportPublication.report_id.desc())
        )
        return list((await self._session.execute(stmt)).scalars())


__all__ = ["ReportPublicationRepository"]
