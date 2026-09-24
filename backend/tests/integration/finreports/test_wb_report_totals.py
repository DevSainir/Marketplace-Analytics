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

from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.models import FinancialReport, LogisticsTransaction
from src.modules.finreports.repos import FinancialReportRepository
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement.reconcile import reconcile_against_wb

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


def _sale(
    report_id: int,
    rrd_id: int,
    for_pay: Decimal,
    oper: str = "Продажа",
    doc_type: str = "Продажа",
) -> LogisticsTransaction:
    """One settlement row (a «Продажа» unless told otherwise) and its payout."""
    return LogisticsTransaction(
        rrd_id=rrd_id,
        workspace_id=WORKSPACE,
        report_id=report_id,
        rr_dt=date(2026, 8, 26),
        supplier_oper_name=oper,
        doc_type_name=doc_type,
        ppvz_for_pay=for_pay,
        nm_id=123456,
    )


async def test_a_report_short_of_its_own_rows_stops_counting_as_held(
    db_session: AsyncSession,
) -> None:
    """NEVA's August, as an assertion.

    Report 981405464 covered 24-30.08 and we held 13.8 % of its money, with the
    header present and the id in every «what do I hold» set. Nothing ever asked
    for the rest: a set difference sees presence, and presence was written
    beside the first batch of rows.

    So presence stops being the test. WB's own `forPaySum` is, and a report that
    does not add up to it goes back on the missing list.
    """
    db_session.add(_held_report(HELD))
    db_session.add(_sale(HELD, 1, Decimal("1000.00")))
    await db_session.flush()
    repo = FinancialReportRepository(db_session)
    await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("7250.00"), Decimal("0"), Decimal("0"))],
    )

    incomplete = await repo.incomplete_report_ids(workspace_id=WORKSPACE)

    assert incomplete == {HELD}


async def test_a_report_that_adds_up_is_left_alone(db_session: AsyncSession) -> None:
    """Otherwise every complete report is re-fetched on every sweep, for ever."""
    db_session.add(_held_report(HELD))
    db_session.add(_sale(HELD, 1, Decimal("1000.00")))
    await db_session.flush()
    repo = FinancialReportRepository(db_session)
    await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("1000.00"), Decimal("0"), Decimal("0"))],
    )

    assert await repo.incomplete_report_ids(workspace_id=WORKSPACE) == set()


async def test_a_report_adds_up_the_way_wb_totals_it(db_session: AsyncSession) -> None:
    """Rows under document type «Возврат» come off, every other row goes on.

    Whatever the operation: the same «Коррекция продаж» is added under «Продажа»
    and subtracted under «Возврат», and a damage compensation counts like a
    sale. The check used to count four named operations and nothing else, so a
    report carrying «Компенсация ущерба» could never add up and was re-fetched
    every tick.
    """
    db_session.add(_held_report(HELD))
    db_session.add_all(
        [
            _sale(HELD, 1, Decimal("1000.00")),
            _sale(HELD, 2, Decimal("200.00"), "Возврат", "Возврат"),
            _sale(HELD, 3, Decimal("874.69"), "Коррекция продаж"),
            _sale(HELD, 4, Decimal("64.13"), "Коррекция продаж", "Возврат"),
            _sale(HELD, 5, Decimal("500.00"), "Компенсация ущерба"),
        ]
    )
    await db_session.flush()
    repo = FinancialReportRepository(db_session)
    await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("2110.56"), Decimal("0"), Decimal("0"))],
    )

    assert await repo.incomplete_report_ids(workspace_id=WORKSPACE) == set()


async def test_a_restatement_inside_the_tolerance_is_not_a_shortfall(
    db_session: AsyncSession,
) -> None:
    """WB revises a settled week, so exact equality would never terminate.

    A report that can never match is re-fetched every sweep for ever. Measured
    on NEVA the two populations separate cleanly: 20 reports inside 0.5 %, the
    worst genuine shortfall at 1.2 %.
    """
    db_session.add(_held_report(HELD))
    db_session.add(_sale(HELD, 1, Decimal("1000.00")))
    await db_session.flush()
    repo = FinancialReportRepository(db_session)
    await repo.refresh_wb_totals(
        workspace_id=WORKSPACE,
        totals=[(HELD, Decimal("1003.00"), Decimal("0"), Decimal("0"))],
    )

    assert await repo.incomplete_report_ids(workspace_id=WORKSPACE) == set()


async def test_a_report_with_no_wb_total_is_not_guessed_at(
    db_session: AsyncSession,
) -> None:
    """Without the oracle there is no evidence either way.

    Every header booked before 2026-09-23 has no WB total on it. Treating those
    as incomplete would re-fetch an entire history on no grounds — «Демо»
    alone holds 143 of them.
    """
    db_session.add(_held_report(HELD))
    await db_session.flush()

    incomplete = await FinancialReportRepository(db_session).incomplete_report_ids(
        workspace_id=WORKSPACE
    )

    assert incomplete == set()


def _header(report_id: int, for_pay_sum: str) -> WBFinanceReportHeader:
    """WB's list entry for a report, carrying only the total under test."""
    return WBFinanceReportHeader.model_validate(
        {
            "reportId": report_id,
            "dateFrom": "2026-08-24",
            "dateTo": "2026-08-30",
            "createDate": "2026-08-31",
            "forPaySum": for_pay_sum,
        }
    )


async def test_a_booked_report_that_adds_up_reconciles_to_zero(db_session: AsyncSession) -> None:
    """The check a harvest runs on every report it books, agreeing with WB.

    Same arithmetic as the completeness check — a «Возврат» document comes off,
    everything else goes on — so a report that the lane counts as held is one
    the alert stays quiet about.
    """
    db_session.add(_held_report(HELD))
    db_session.add_all(
        [
            _sale(HELD, 1, Decimal("1000.00")),
            _sale(HELD, 2, Decimal("200.00"), "Возврат", "Возврат"),
            _sale(HELD, 3, Decimal("64.13"), "Коррекция продаж", "Возврат"),
        ]
    )
    await db_session.flush()

    gap = await reconcile_against_wb(
        db_session, header=_header(HELD, "735.87"), workspace_id=WORKSPACE, name="Демо"
    )

    assert gap == Decimal("0")


async def test_a_booked_report_short_of_wb_s_total_reports_the_gap(
    db_session: AsyncSession,
) -> None:
    """WB's figure minus ours: positive means we hold less than WB paid."""
    db_session.add(_held_report(HELD))
    db_session.add(_sale(HELD, 1, Decimal("1000.00")))
    await db_session.flush()

    gap = await reconcile_against_wb(
        db_session, header=_header(HELD, "1250.00"), workspace_id=WORKSPACE, name="Демо"
    )

    assert gap == Decimal("250.00")


async def test_a_report_wb_lists_money_in_is_not_booked_over_no_rows(
    db_session: AsyncSession,
) -> None:
    """An empty answer for a report WB says holds money is «not yet», not «done».

    WB lists a report before it serves the rows — 983241109 came eight days
    late. Booking the header over nothing would count the id as held and never
    ask again.
    """
    ingestion = build_ingestion(db_session)

    booked = await ingestion.record_report_header(
        _header(NOT_HELD, "1000.00"), workspace_id=WORKSPACE
    )

    assert booked is False
    assert await db_session.get(FinancialReport, NOT_HELD) is None


async def test_a_report_that_owes_nothing_may_be_booked_empty(db_session: AsyncSession) -> None:
    """Every WB total zero: nothing is owed, so an empty report is a real one."""
    ingestion = build_ingestion(db_session)

    booked = await ingestion.record_report_header(_header(NOT_HELD, "0"), workspace_id=WORKSPACE)

    assert booked is True
    assert await db_session.get(FinancialReport, NOT_HELD) is not None
