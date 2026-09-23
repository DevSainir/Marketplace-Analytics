"""What the daily tail's two halves both need: WB's list, and the frontier.

Two functions, shared because the harvest and the day-later check ask WB the same
question and read the same boundary — and because a second copy of either is a
place for the two to drift into disagreeing about what «already settled» means.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.integrations.wildberries.clients import ReportPeriod, WBFinanceReportsClient
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.repos import (
    FinancialReportRepository,
    ListedTotals,
    SettlementWatermarkRepository,
)
from src.modules.finreports.tasks.spans import settlement_frontier
from src.modules.workspaces.contract import WorkspaceTokenBundle


async def list_daily(
    *, tokens: WorkspaceTokenBundle, span: tuple[date, date]
) -> list[WBFinanceReportHeader]:
    """Ask WB which daily reports it has formed over ``span``.

    One request, on the list bucket rather than the detail one — the separation
    is what makes «is there anything to fetch» cost nothing the fetching needs.
    """
    async with WBFinanceReportsClient(settings, token=tokens.finance) as client:
        return list(
            await client.list_reports(date_from=span[0], date_to=span[1], period=ReportPeriod.DAILY)
        )


async def settled_frontier(*, workspace_id: uuid.UUID) -> date | None:
    """How far the WEEKLY lane has actually settled this workspace.

    The earlier of the walk's own watermark and the newest report's stated end —
    see :func:`~src.modules.finreports.tasks.spans.settlement_frontier` for why
    neither date is safe alone. Everything in the tail is defined against it: the
    days it may cover, and the reports it must stop re-reading because a
    settlement document now owns their rows.

    Args:
        workspace_id: Tenancy scope.

    Returns:
        The frontier, or ``None`` for a workspace the weekly lane has never
        covered.
    """
    async with AsyncSessionLocal() as session:
        return settlement_frontier(
            watermark=await SettlementWatermarkRepository(session).get(workspace_id=workspace_id),
            covered_through=await FinancialReportRepository(session).latest_settled_date(
                workspace_id=workspace_id
            ),
        )


def listed_totals(header: WBFinanceReportHeader) -> ListedTotals:
    """WB's own totals for one listed report."""
    return ListedTotals(
        for_pay=header.for_pay_sum,
        retail_amount=header.retail_amount_sum,
        bank_payment=header.bank_payment_sum,
    )


__all__ = ["list_daily", "listed_totals", "settled_frontier"]
