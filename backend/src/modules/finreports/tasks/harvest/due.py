"""Which sellers are still owed a report today — answered from our own tables.

A scheduled tick used to ask WB about every seller on every run: two
`sales-reports/list` requests each, 58 runs a day, to find the two or three
reports a day actually brings. But what a day can bring is known in advance:

* **a daily report for yesterday**, served in the small hours (seen at 01:01,
  03:06 and 04:01 on one workspace, 09.2026);
* **a weekly report only after a period closes** — a Sunday or a month end,
  created the next day (142 of 142 reports) and served from about 10:00.

So a seller holding both has nothing left to come today, and a tick can say so
from SQL without spending a request. The reports that break the calendar —
served days late, back-dated — are the nightly reconciliation's job, which
walks every seller regardless of this.

Only scheduled ticks are gated. "Refresh", a new workspace's first harvest and
the nightly pass always ask WB.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.core.database import AsyncSessionLocal
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.repos.daily_settlement import DailySettlementRepository


def last_period_end(on_or_before: date) -> date:
    """The latest day on or before ``on_or_before`` that closes a weekly period.

    WB closes a settlement period on Sunday and on the last day of a month, so a
    week that straddles two months is two reports.
    """
    day = on_or_before
    while day.weekday() != 6 and (day + timedelta(days=1)).day != 1:
        day -= timedelta(days=1)
    return day


def owes_a_report(*, today: date, settled_through: date | None, tail_through: date | None) -> bool:
    """Whether WB may still serve this seller something we do not hold.

    Args:
        today: Today in Moscow time.
        settled_through: The newest weekly report's ``date_to``, or ``None``.
        tail_through: The newest daily report's day, or ``None``.

    Returns:
        True while the weekly report for the last closed period is missing, or
        while nothing — weekly or daily — covers yesterday.
    """
    if settled_through is None:
        return True
    yesterday = today - timedelta(days=1)
    if settled_through < last_period_end(yesterday):
        return True
    return max(settled_through, tail_through or settled_through) < yesterday


async def sellers_owed_a_report(workspace_ids: list[uuid.UUID], *, today: date) -> set[uuid.UUID]:
    """The subset of ``workspace_ids`` that :func:`owes_a_report` holds for.

    Two indexed ``max()`` reads per seller and no WB request.
    """
    owed: set[uuid.UUID] = set()
    async with AsyncSessionLocal() as session:
        reports = FinancialReportRepository(session)
        daily = DailySettlementRepository(session)
        for workspace_id in workspace_ids:
            if owes_a_report(
                today=today,
                settled_through=await reports.latest_settled_date(workspace_id=workspace_id),
                tail_through=await daily.covered_through(workspace_id=workspace_id),
            ):
                owed.add(workspace_id)
    return owed


__all__ = ["last_period_end", "owes_a_report", "sellers_owed_a_report"]
