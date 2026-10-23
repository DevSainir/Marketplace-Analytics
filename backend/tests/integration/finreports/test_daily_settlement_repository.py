"""The daily tail's bookkeeping, in real SQL.

Everything the day-later verification concludes rests on four statements this
repository runs: an md5 over `string_agg` of the rows, an upsert that must clear
an old verdict, a queue ordered and filtered by age, and a verdict write scoped
to one workspace. Each has been unit-tested only through fakes, which is to say
not at all — `string_agg` ordering and `ON CONFLICT` semantics are PostgreSQL's,
not Python's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.models.daily_settlement_report import DailyReportVerdict
from src.modules.finreports.repos.daily_settlement import (
    DailySettlementRepository,
    Fingerprint,
    ListedTotals,
)
from tests.integration.finreports.conftest import OTHER_WORKSPACE, WORKSPACE
from tests.support import wb_labels as wb

pytestmark = pytest.mark.integration

DAILY = 202609210000001
DAY = date(2026, 9, 21)
NO_TOTALS = ListedTotals(for_pay=None, retail_amount=None, bank_payment=None)


def _row(rrd_id: int, payout: str) -> LogisticsTransaction:
    """One sale row of the daily report."""
    return LogisticsTransaction(
        rrd_id=rrd_id,
        report_id=DAILY,
        workspace_id=WORKSPACE,
        nm_id=123,
        supplier_oper_name=wb.SALE,
        doc_type_name=wb.SALE,
        rr_dt=DAY,
        currency_name="KGS",
        ppvz_for_pay=Decimal(payout),
    )


async def _ingest(
    repo: DailySettlementRepository, workspace: uuid.UUID = WORKSPACE, report_id: int = DAILY
) -> None:
    """Record the daily report with whatever rows it holds now."""
    await repo.record_ingest(
        workspace_id=workspace,
        report_id=report_id,
        day=DAY,
        create_dt=DAY + timedelta(days=1),
        fingerprint=await repo.fingerprint(workspace_id=workspace, report_id=report_id),
        totals=NO_TOTALS,
    )


async def test_the_fingerprint_moves_with_an_amount_and_not_without_one(
    db_session: AsyncSession,
) -> None:
    """Same rows, same digest; one kopeck different, a different digest.

    That is the whole of the «did WB revise this day» question, so both halves
    matter: a digest that moved on nothing would report changes WB never made.
    """
    db_session.add_all([_row(1, "100.00"), _row(2, "250.00")])
    await db_session.flush()
    repo = DailySettlementRepository(db_session)
    first = await repo.fingerprint(workspace_id=WORKSPACE, report_id=DAILY)
    again = await repo.fingerprint(workspace_id=WORKSPACE, report_id=DAILY)

    row = await db_session.get(LogisticsTransaction, 2)
    assert row is not None
    row.ppvz_for_pay = Decimal("250.01")
    await db_session.flush()
    revised = await repo.fingerprint(workspace_id=WORKSPACE, report_id=DAILY)

    assert first == again
    assert first.rows == revised.rows == 2
    assert first.digest != revised.digest


async def test_a_report_with_no_rows_has_an_empty_fingerprint(db_session: AsyncSession) -> None:
    """Zero rows and no digest, rather than an md5 of nothing that could match."""
    repo = DailySettlementRepository(db_session)

    assert await repo.fingerprint(workspace_id=WORKSPACE, report_id=DAILY) == Fingerprint(0, "")


async def test_re_ingesting_a_report_puts_it_back_on_the_queue(db_session: AsyncSession) -> None:
    """A retried report is verified against what it now holds, not its first half.

    The upsert clears the verdict; if it did not, a report first recorded
    half-fetched and then completed would keep a verdict about the half.
    """
    db_session.add(_row(1, "100.00"))
    await db_session.flush()
    repo = DailySettlementRepository(db_session)
    await _ingest(repo)
    await repo.record_verification(
        workspace_id=WORKSPACE, report_id=DAILY, verdict=DailyReportVerdict.UNCHANGED
    )

    await _ingest(repo)

    later = datetime.now(UTC) + timedelta(hours=25)
    due = await repo.due_for_verification(
        workspace_id=WORKSPACE, after_hours=24, limit=10, now=later
    )
    assert [pending.report_id for pending in due] == [DAILY]


async def test_the_queue_waits_the_full_day_and_skips_what_is_verified(
    db_session: AsyncSession,
) -> None:
    """Not due before 24 h; due after; gone once a verdict is recorded."""
    repo = DailySettlementRepository(db_session)
    await _ingest(repo)
    soon = datetime.now(UTC) + timedelta(hours=23)
    later = datetime.now(UTC) + timedelta(hours=25)

    early = await repo.due_for_verification(
        workspace_id=WORKSPACE, after_hours=24, limit=10, now=soon
    )
    due = await repo.due_for_verification(
        workspace_id=WORKSPACE, after_hours=24, limit=10, now=later
    )
    await repo.record_verification(
        workspace_id=WORKSPACE, report_id=DAILY, verdict=DailyReportVerdict.SUPERSEDED
    )
    after = await repo.due_for_verification(
        workspace_id=WORKSPACE, after_hours=24, limit=10, now=later
    )

    assert (len(early), len(due), len(after)) == (0, 1, 0)


async def test_a_verdict_is_written_only_to_its_own_workspace(db_session: AsyncSession) -> None:
    """Named with another workspace, the write touches nothing.

    The worker is the table owner, so row-level security does not stand behind
    this UPDATE; the `WHERE` on `workspace_id` is the only tenancy check.
    """
    repo = DailySettlementRepository(db_session)
    await _ingest(repo)

    await repo.record_verification(
        workspace_id=OTHER_WORKSPACE, report_id=DAILY, verdict=DailyReportVerdict.WITHDRAWN
    )

    later = datetime.now(UTC) + timedelta(hours=25)
    due = await repo.due_for_verification(
        workspace_id=WORKSPACE, after_hours=24, limit=10, now=later
    )
    assert [pending.report_id for pending in due] == [DAILY]


async def test_a_closed_day_keeps_only_what_the_weekly_report_rewrote(
    db_session: AsyncSession,
) -> None:
    """On a closed day, rows still under a daily id go; weekly rows and open days stay.

    The weekly report rewrites every row it shares with the daily one under its
    own id, so a daily id left on a settled day is a row WB kept out of the
    settlement — and the settlement is the document.
    """
    open_daily = DAILY + 1
    left_out = _row(1, "100.00")
    rewritten = _row(2, "200.00")
    rewritten.report_id = 848_045_043
    still_open = _row(3, "300.00")
    still_open.report_id = open_daily
    still_open.rr_dt = DAY + timedelta(days=2)
    db_session.add_all([left_out, rewritten, still_open])
    await db_session.flush()
    repo = DailySettlementRepository(db_session)
    await _ingest(repo)
    await repo.record_ingest(
        workspace_id=WORKSPACE,
        report_id=open_daily,
        day=DAY + timedelta(days=2),
        create_dt=None,
        fingerprint=Fingerprint(1, "x"),
        totals=NO_TOTALS,
    )

    dropped = await repo.drop_closed_days(
        workspace_id=WORKSPACE, through=DAY, since=DAY - timedelta(days=28)
    )
    db_session.expire_all()

    assert dropped == 1
    assert await db_session.get(LogisticsTransaction, 1) is None
    assert await db_session.get(LogisticsTransaction, 2) is not None
    assert await db_session.get(LogisticsTransaction, 3) is not None


async def test_dropping_a_report_s_rows_is_scoped_to_its_workspace(
    db_session: AsyncSession,
) -> None:
    """Named with another workspace, the delete removes nothing."""
    db_session.add(_row(1, "100.00"))
    await db_session.flush()
    repo = DailySettlementRepository(db_session)

    foreign = await repo.drop_rows(workspace_id=OTHER_WORKSPACE, report_ids=[DAILY])
    own = await repo.drop_rows(workspace_id=WORKSPACE, report_ids=[DAILY])

    assert (foreign, own) == (0, 1)
