"""The harvest's view of the report ledger — what we hold, and what WB says of it.

Split out of :mod:`fleet` because it is a different question from «who gets
harvested this tick». Both functions here read or write ``financial_report``,
the table whose row set IS the answer to «which reports does this workspace
hold» — and that makes both of them places where a careless write would tell
the walk it had already fetched something it had not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import WBFinanceReportsClient
from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.constants import RECONCILE_LOOKBACK_DAYS, WB_REPORTS_EPOCH
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


async def record_wb_totals(
    *, workspace_id: uuid.UUID, listed: Sequence[WBFinanceReportHeader]
) -> None:
    """Store WB's per-report sums on the reports this workspace already holds.

    Never raises. These figures are a cross-check rather than a source — the
    P&L is derived from the settlement rows, not from them — so failing to
    record them must not cost a tick the harvest it was about to do.

    Args:
        workspace_id: Tenancy scope.
        listed: Whatever ``sales-reports/list`` named this tick, held or not.
    """
    if not listed:
        return
    try:
        async with AsyncSessionLocal() as session:
            updated = await FinancialReportRepository(session).refresh_wb_totals(
                workspace_id=workspace_id,
                totals=[
                    (h.report_id, h.for_pay_sum, h.retail_amount_sum, h.bank_payment_sum)
                    for h in listed
                ],
            )
            await session.commit()
        logger.debug("finreports: refreshed WB totals on %d held report(s).", updated)
    except Exception:
        logger.warning(
            "finreports: could not record WB's report totals; the harvest carries on.",
            exc_info=True,
        )


async def refresh_archive_totals(*, tokens: WorkspaceTokenBundle, today: date) -> None:
    """Put WB's own totals on every report this workspace holds, archive included.

    The ordinary tick lists 45 days, so a report older than that only got its
    totals from the history backfill — which runs once, for a NEW workspace.
    A workspace that predates the totals had them on eight of 143 reports, and the
    completeness check and the WB reconciliation are blind wherever a total is
    missing. One list request answers for the whole history at any width
    (measured 2026-09-23), so the nightly pass spends it.

    Never raises, for the same reason :func:`record_wb_totals` does not.

    Args:
        tokens: The workspace's decrypted WB credentials.
        today: Today in Moscow time.
    """
    if not tokens.finance:
        return
    try:
        async with WBFinanceReportsClient(settings, token=tokens.finance) as client:
            listed = await client.list_reports(date_from=WB_REPORTS_EPOCH, date_to=today)
    except IntegrationError as exc:
        logger.warning(
            "finreports: could not list %s's whole history for WB's totals: %s", tokens.name, exc
        )
        return
    await record_wb_totals(workspace_id=tokens.workspace_id, listed=listed)


async def reports_to_re_walk(
    *, report_repo_for: uuid.UUID, today: date
) -> tuple[MissingReport, ...]:
    """The held reports a thorough pass should ask WB for again.

    «Which ids am I missing» cannot see an amendment to a report already on
    file, and amendments are exactly what the reconciliation pass exists for —
    WB revises a settled week for up to a fortnight. So a thorough pass with
    nothing missing re-walks what it holds inside
    :data:`RECONCILE_LOOKBACK_DAYS`, upserting by ``rrd_id`` over the top.

    Plus every OLDER report that does not add up to WB's own total. The forward
    tick only looks back 45 days, and the history backfill runs once, so a short
    archive report on an established workspace had nothing left that would ever
    ask for it again.

    Args:
        report_repo_for: Workspace whose held reports to re-walk.
        today: Today in Moscow time.

    Carries no WB header, so the walk re-writes the rows and leaves the header
    alone. That is right for a re-walk — the header is already there, and the
    header's job is to say «this report is held», which it already does. What
    it does NOT do is refresh WB's own totals on a week WB has restated; that
    needs the list entry, which this function does not have.

    Returns:
        The reports, oldest first.
    """
    since = today - timedelta(days=RECONCILE_LOOKBACK_DAYS)
    async with AsyncSessionLocal() as session:
        repo = FinancialReportRepository(session)
        periods = await repo.list_periods(workspace_id=report_repo_for)
        short = await repo.incomplete_report_ids(workspace_id=report_repo_for)
    return tuple(
        MissingReport(report_id=report_id, date_to=date_to, date_from=date_from)
        for report_id, date_from, date_to in sorted(periods, key=lambda row: row[2])
        if date_to >= since or report_id in short
    )


__all__ = ["record_wb_totals", "refresh_archive_totals", "reports_to_re_walk"]
