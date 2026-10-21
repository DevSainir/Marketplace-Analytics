"""The P&L's period picker reaches every day the statement can show.

Since the daily tail landed, the statement runs past the newest weekly report:
on a Monday morning the week before is in the P&L day by day while its weekly
report is still WB's. The picker was bounded by the weekly reports alone, so it
locked exactly those days (12.10.2026: data to 11.10, picker to 04.10).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.services import PeriodService

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


class _FakeReports:
    """The weekly periods on file: 28.09-30.09 and 01.10-04.10."""

    async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
        return [
            (992863498, date(2026, 10, 1), date(2026, 10, 4)),
            (992545862, date(2026, 9, 28), date(2026, 9, 30)),
        ]


class _FakeDaily:
    """The daily tail, reaching ``through``."""

    def __init__(self, through: date | None) -> None:
        self._through = through

    async def covered_through(self, *, workspace_id: uuid.UUID) -> date | None:
        return self._through


def _service(daily_through: date | None) -> PeriodService:
    """A PeriodService over the weekly periods and a daily tail to ``daily_through``."""
    return PeriodService(
        report_repo=_FakeReports(),  # type: ignore[arg-type]
        daily_repo=_FakeDaily(daily_through),  # type: ignore[arg-type]
    )


async def test_the_daily_tail_past_the_last_week_reaches_the_picker() -> None:
    """Data to 11.10 under a weekly report to 04.10: the picker must reach 11.10."""
    service = _service(date(2026, 10, 11))

    weeks = await service.list_weeks(workspace_id=WORKSPACE)

    assert weeks.provisional_through == date(2026, 10, 11)


async def test_a_tail_behind_the_weekly_report_adds_nothing() -> None:
    """Once the weekly report covers the tail, the weeks alone bound the picker."""
    service = _service(date(2026, 10, 3))

    weeks = await service.list_weeks(workspace_id=WORKSPACE)

    assert weeks.provisional_through is None
