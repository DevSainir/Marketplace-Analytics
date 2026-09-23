"""Recording WB's own per-report totals must never invent a report.

``financial_report``'s row set is the answer to «which reports does this
workspace hold» — :meth:`FinancialReportRepository.report_ids_since` reads it,
and the settlement walk subtracts it from WB's list to decide what to fetch. So
a write that inserts a header for a report whose rows have NOT been fetched does
not merely add a row: it tells the walk the report is already in hand, and the
walk never asks for it again. Rows missing, no error, no gap in the ids.

That is why :meth:`refresh_wb_totals` is an UPDATE and not the upsert every
other write in this module is, and why the harvest may hand it WB's whole list
— held reports and unheld alike — without filtering first. The safety is in the
statement, so no caller can forget it.

Real SQL, because the property being pinned is «this statement cannot insert»,
which is a fact about the statement rather than about the code around it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos import FinancialReportRepository

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ac01")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ac02")

HELD = 910000001
NOT_HELD = 910000002


def _held_report(report_id: int, *, workspace_id: uuid.UUID = WORKSPACE) -> FinancialReport:
    """A report whose rows we have already fetched — hence a header on file."""
    return FinancialReport(
        report_id=report_id,
        workspace_id=workspace_id,
        date_from=date(2026, 8, 24),
        date_to=date(2026, 8, 30),
        currency="KGS",
    )


async def test_wb_s_totals_land_on_a_report_we_hold(db_session: AsyncSession) -> None:
    """The ordinary case, and the reason the columns exist.

    `retailAmountSum`, `forPaySum` and `bankPaymentSum` are served by
    `sales-reports/list` and appear on no settlement row, so this is the only
    way they are ever stored. They are the one figure the P&L can be checked
    against that is not our own arithmetic.
    """
    db_session.add(_held_report(HELD))
    await db_session.flush()
    repo = FinancialReportRepository(db_session)

    updated = await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("123456.78"), Decimal("200000.00"), Decimal("99999.99"))],
    )

    assert updated == 1
    stored = await db_session.get(FinancialReport, HELD)
    assert stored is not None
    assert stored.wb_for_pay_sum == Decimal("123456.78")
    assert stored.wb_retail_amount_sum == Decimal("200000.00")
    assert stored.wb_bank_payment_sum == Decimal("99999.99")


async def test_a_report_we_do_not_hold_is_not_created_by_recording_its_totals(
    db_session: AsyncSession,
) -> None:
    """The trap this whole method is shaped around.

    WB's list names reports we have not fetched — that is what the list is FOR.
    An upsert here would write a header for each of them, and every one would
    then read as held: the walk would subtract it from WB's list, find nothing
    missing, and the seller's P&L would be short a week with nothing anywhere
    saying so.
    """
    repo = FinancialReportRepository(db_session)

    updated = await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(NOT_HELD, Decimal("1.00"), Decimal("2.00"), Decimal("3.00"))],
    )

    assert updated == 0
    assert await db_session.get(FinancialReport, NOT_HELD) is None
    held = await repo.report_ids_since(workspace_id=WORKSPACE, since=date(2020, 1, 1))
    assert NOT_HELD not in held, "an unfetched report was booked as held"


async def test_one_tenants_list_cannot_touch_another_tenants_report(
    db_session: AsyncSession,
) -> None:
    """Report ids are WB's, and WB's namespace is not ours to assume unique.

    The workspace is part of the match rather than a filter applied afterwards,
    so a tenant whose list happens to name an id another tenant holds writes
    nothing — instead of quietly restating a stranger's week.
    """
    db_session.add(_held_report(HELD, workspace_id=OTHER_WORKSPACE))
    await db_session.flush()
    repo = FinancialReportRepository(db_session)

    updated = await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("1.00"), Decimal("2.00"), Decimal("3.00"))],
    )

    assert updated == 0
    stranger = await db_session.get(FinancialReport, HELD)
    assert stranger is not None
    assert stranger.wb_for_pay_sum is None


async def test_recording_nothing_writes_nothing(db_session: AsyncSession) -> None:
    """A tick whose list came back empty must not cost a statement.

    Every tick calls this, for every workspace, whether or not anything was
    missing — so the empty case is the common one on a quiet fleet.
    """
    before = (
        await db_session.execute(select(func.count()).select_from(FinancialReport))
    ).scalar_one()

    updated = await FinancialReportRepository(db_session).refresh_wb_totals(
        workspace_id=WORKSPACE, totals=[]
    )

    after = (
        await db_session.execute(select(func.count()).select_from(FinancialReport))
    ).scalar_one()
    assert (updated, after) == (0, before)
