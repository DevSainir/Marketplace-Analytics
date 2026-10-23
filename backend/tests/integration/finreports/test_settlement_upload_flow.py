"""A weekly report uploaded by hand — what it writes, what it refuses, how it hands over.

The rule, as the owner put it on 2026-10-12: if we lack the report, its rows go
into the P&L; if we hold it, nothing is written and the seller is told so, after
checking the two are the same; when WB's API serves it, the rows are compared
and the API's — with WB's row id and true date — take over.

Real Postgres: the comparison streams our rows by ``rr_dt``, the ids come from a
sequence, and the hand-over deletes by the sign of ``rrd_id`` — all of it SQL.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.modules.finreports.models import LogisticsTransaction, SettlementUpload, UploadStatus
from src.modules.finreports.repos import (
    LogisticsTransactionRepository,
    SettlementUploadRepository,
)
from src.modules.finreports.services.settlement_upload import SettlementUploadService
from src.modules.finreports.services.settlement_upload.reconcile import settle_upload_on_booking
from src.modules.finreports.services.settlement_upload.workbook import (
    HEADER_FOR,
    iter_report_rows,
)
from src.modules.finreports.tasks import settlement_upload as task
from tests.support import wb_labels as wb
from tests.support.wb_weekly_report import (
    FILENAME,
    REPORT_ID,
    weekly_row,
    weekly_workbook,
    weekly_zip,
)

pytestmark = pytest.mark.integration

#: WB's headers for the columns these rows set.
SALE_DT, DELIVERY = HEADER_FOR["sale_dt"], HEADER_FOR["delivery_rub"]

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000c801")
USER = uuid.UUID("019f657a-0000-7000-8000-00000000c802")
DAILY_REPORT = 938364620261006

#: Three rows of the 05.10-11.10 week; the first is a logistics charge for a
#: sale dated before the week, which WB books on the week's first day.
ROWS = [
    weekly_row({SALE_DT: "2026-10-03", DELIVERY: 46.75}),
    weekly_row({SALE_DT: "2026-10-06"}),
    weekly_row(
        {
            HEADER_FOR["supplier_oper_name"]: wb.SALE,
            HEADER_FOR["doc_type_name"]: wb.SALE,
            SALE_DT: "2026-10-11",
            DELIVERY: 0,
            HEADER_FOR["ppvz_for_pay"]: 1043.26,
            HEADER_FOR["quantity"]: 1,
        }
    ),
]


@pytest.fixture(autouse=True)
def worker(monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]):
    """Point the worker at the test transaction, on Monday 12.10.2026."""
    monkeypatch.setattr(task, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(task, "moscow_today", lambda: date(2026, 10, 12))


@pytest.fixture(autouse=True)
async def settled_before(db_session: AsyncSession) -> None:
    """A row of an earlier week, which is where the workspace's currency is read from."""
    db_session.add(
        LogisticsTransaction(
            rrd_id=1,
            report_id=992863498,
            workspace_id=WORKSPACE,
            nm_id=1,
            rr_dt=date(2026, 10, 1),
            currency_name="KGS",
        )
    )
    await db_session.commit()


async def _upload(session: AsyncSession, rows: list[dict[str, Any]] = ROWS) -> SettlementUpload:
    """Upload a file the way the route does, run the worker on it, and re-read it."""
    upload = await SettlementUploadService(upload_repo=SettlementUploadRepository(session)).accept(
        workspace_id=WORKSPACE,
        user_id=USER,
        filename=FILENAME,
        data=weekly_zip(weekly_workbook(rows)),
    )
    await session.commit()
    await task.process_settlement_upload(upload.id)
    return await _reread(session, upload.id)


async def _reread(session: AsyncSession, upload_id: uuid.UUID) -> SettlementUpload:
    session.expire_all()
    found = await session.get(SettlementUpload, upload_id)
    assert found is not None
    return found


async def _hold(session: AsyncSession, rows: list[dict[str, Any]], *, report_id: int) -> None:
    """Put rows into the table as WB's API would serve them: real ids, true days."""
    parsed = list(iter_report_rows(weekly_workbook(rows)))
    await LogisticsTransactionRepository(session).bulk_upsert(
        [
            row
            | {
                "rrd_id": 1000 + index,
                "report_id": report_id,
                "workspace_id": WORKSPACE,
                "currency_name": "KGS",
                "rr_dt": max(row["sale_dt"], date(2026, 10, 5)),
            }
            for index, row in enumerate(parsed)
        ],
        conflict_columns=["rrd_id"],
        update_columns=["report_id"],
    )
    await session.commit()


async def _week(session: AsyncSession) -> list[LogisticsTransaction]:
    """Every row of the week, oldest day first."""
    stmt = (
        select(LogisticsTransaction)
        .where(LogisticsTransaction.workspace_id == WORKSPACE)
        .where(LogisticsTransaction.rr_dt >= date(2026, 10, 5))
        .order_by(LogisticsTransaction.rr_dt, LogisticsTransaction.rrd_id)
    )
    return list((await session.execute(stmt)).scalars())


async def test_a_report_we_lack_stands_in_the_pl_on_the_weeks_days(
    db_session: AsyncSession,
) -> None:
    """Written whole, with ids no WB row can have and days clamped into the week."""
    upload = await _upload(db_session)

    rows = await _week(db_session)
    assert upload.status == UploadStatus.WRITTEN
    assert [row.rr_dt for row in rows] == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 11)]
    assert all(row.rrd_id < 0 and row.report_id == REPORT_ID for row in rows)
    assert {row.currency_name for row in rows} == {"KGS"}


async def test_the_same_file_twice_is_held_already_and_written_once(
    db_session: AsyncSession,
) -> None:
    """The second upload finds every row in place and says so, writing nothing."""
    await _upload(db_session)

    upload = await _upload(db_session)

    assert upload.status == UploadStatus.ALREADY_HELD
    assert len(await _week(db_session)) == 3
    assert upload.message.startswith("We already have this report")


async def test_a_week_the_daily_reports_already_gave_us_is_confirmed_not_doubled(
    db_session: AsyncSession,
) -> None:
    """992915233's own case: every row was in from the daily lane before the file came."""
    await _hold(db_session, ROWS, report_id=DAILY_REPORT)

    upload = await _upload(db_session)

    assert upload.status == UploadStatus.ALREADY_HELD
    assert all(row.rrd_id > 0 for row in await _week(db_session))


async def test_a_daily_report_that_never_came_is_filled_from_the_file(
    db_session: AsyncSession,
) -> None:
    """We hold one row of three, and it is in the file: the other two are written."""
    await _hold(db_session, ROWS[1:2], report_id=DAILY_REPORT)

    upload = await _upload(db_session)

    rows = await _week(db_session)
    assert upload.status == UploadStatus.WRITTEN
    assert sorted(row.rrd_id > 0 for row in rows) == [False, False, True]
    assert upload.rows_written == 2


async def test_a_row_we_hold_that_the_file_lacks_writes_nothing(db_session: AsyncSession) -> None:
    """Both are WB's documents; a disagreement is for a person, never for a guess."""
    other = weekly_row({SALE_DT: "2026-10-07", DELIVERY: 99})
    await _hold(db_session, [other], report_id=DAILY_REPORT)

    upload = await _upload(db_session)

    assert upload.status == UploadStatus.DIVERGED
    assert [row.rrd_id > 0 for row in await _week(db_session)] == [True]


async def test_a_week_still_running_is_refused_with_the_reason(db_session: AsyncSession) -> None:
    """WB has no report for a week that has not ended."""
    upload = await _upload(db_session, [weekly_row({SALE_DT: "2026-10-12"})])

    assert upload.status == UploadStatus.FAILED
    assert "isn't over yet" in upload.message
    assert upload.payload is None


async def test_the_apis_report_takes_over_from_the_matching_file(db_session: AsyncSession) -> None:
    """Same rows: the file's go, the API's stay, and the upload is confirmed."""
    upload = await _upload(db_session)
    await _hold(db_session, ROWS, report_id=REPORT_ID)

    await settle_upload_on_booking(
        SettlementUploadRepository(db_session), workspace_id=WORKSPACE, report_id=REPORT_ID
    )
    await db_session.commit()

    assert all(row.rrd_id > 0 for row in await _week(db_session))
    assert (await _reread(db_session, upload.id)).status == UploadStatus.CONFIRMED


async def test_an_api_report_unlike_the_file_still_takes_over_but_is_flagged(
    db_session: AsyncSession,
) -> None:
    """The week may not be counted twice; the difference is recorded for a person."""
    upload = await _upload(db_session)
    await _hold(db_session, ROWS[:2], report_id=REPORT_ID)

    await settle_upload_on_booking(
        SettlementUploadRepository(db_session), workspace_id=WORKSPACE, report_id=REPORT_ID
    )
    await db_session.commit()

    assert len(await _week(db_session)) == 2
    assert (await _reread(db_session, upload.id)).status == UploadStatus.REPLACED_DIVERGED


async def test_uploaded_rows_never_let_the_report_count_as_served(db_session: AsyncSession) -> None:
    """Booked over the file's rows, the header would mark the report held and stop the fetch."""
    await _upload(db_session)

    served = await LogisticsTransactionRepository(db_session).holds_report(
        workspace_id=WORKSPACE, report_id=REPORT_ID
    )

    assert served is False
