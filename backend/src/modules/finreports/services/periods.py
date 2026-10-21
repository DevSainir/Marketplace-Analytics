"""The weeks the period picker may offer — read side of every finreports page.

The SPA builds its period selector from this answer: the full settlement span
picks a default window and bounds the date picker. It reads three facts and
writes nothing: the weekly reports on file, how far the provisional daily tail
reaches, and any hand-uploaded report standing in for one WB has not served.
"""

from __future__ import annotations

import uuid

from src.modules.finreports.repos import (
    DailySettlementRepository,
    FinancialReportRepository,
    SettlementUploadRepository,
)
from src.modules.finreports.schemas.pnl import WeekPeriod, WeeksResponse


class PeriodService:
    """Lists the settlement periods one workspace has data for."""

    def __init__(
        self,
        *,
        report_repo: FinancialReportRepository,
        daily_repo: DailySettlementRepository | None = None,
        upload_repo: SettlementUploadRepository | None = None,
    ) -> None:
        """Wire the service to its sources.

        Args:
            report_repo: Source of the harvested weekly report periods.
            daily_repo: Source of how far the provisional daily tail reaches.
            upload_repo: Source of the hand-uploaded reports standing in.
        """
        self._reports = report_repo
        self._daily = daily_repo
        self._uploads = upload_repo

    async def list_weeks(self, *, workspace_id: uuid.UUID) -> WeeksResponse:
        """Return the selectable weekly periods (newest first) and the daily reach.

        The picker is bounded by what the statement can show, and since the
        daily tail landed that runs past the last weekly report: on a Monday
        morning the week before is in the P&L day by day while its weekly report
        is still WB's. Bounded by the weeks alone, the calendar locked exactly
        the days a seller opens it for (12.10.2026: data to 11.10, picker to 04.10).
        """
        periods = await self._reports.list_periods(workspace_id=workspace_id)
        settled = max((dt for (_, _, dt) in periods), default=None)
        tail = await self._daily.covered_through(workspace_id=workspace_id) if self._daily else None
        # An uploaded week is in the statement too, whether or not a daily
        # report ever covered its days.
        for upload in (
            await self._uploads.standing(workspace_id=workspace_id) if self._uploads else []
        ):
            if upload.date_to and (tail is None or upload.date_to > tail):
                tail = upload.date_to
        weeks = [WeekPeriod(report_id=rid, date_from=df, date_to=dt) for (rid, df, dt) in periods]
        return WeeksResponse(
            weeks=weeks,
            provisional_through=tail if tail and settled and tail > settled else None,
        )


__all__ = ["PeriodService"]
