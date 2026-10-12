"""When WB's API first names a report, kept so the lag behind WB's site is measured.

On 12.10.2026 report 992915233 was on WB's site by 08:00 and absent from
``sales-reports/list`` at 08:05, and nothing on file could say when the API
caught up. Each row of the log says «reached the API between A and B»: A the
previous list answer that did not name the report, B the first that did.

Real Postgres for ``ON CONFLICT DO NOTHING`` and real Redis for ``SET … GET``,
the two halves that make the first sighting stick and the bound atomic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.repos import ReportPublicationRepository
from src.modules.finreports.tasks import publication_log
from src.modules.finreports.tasks.publication_log import log_first_listings

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000c701")
OLD_REPORT = 992863498
NEW_REPORT = 992915233
MONDAY_0800 = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
MONDAY_0815 = datetime(2026, 10, 12, 5, 15, tzinfo=UTC)
MONDAY_0830 = datetime(2026, 10, 12, 5, 30, tzinfo=UTC)


def _header(report_id: int, date_from: date, date_to: date) -> WBFinanceReportHeader:
    """One list entry, as WB serves it."""
    return WBFinanceReportHeader.model_validate(
        {
            "reportId": report_id,
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "createDate": date(2026, 10, 12).isoformat(),
        }
    )


OLD = _header(OLD_REPORT, date(2026, 10, 1), date(2026, 10, 4))
NEW = _header(NEW_REPORT, date(2026, 10, 5), date(2026, 10, 11))


@pytest.fixture
def logged(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    redis_client: Any,
) -> Any:
    """Point the log at the test transaction and the test Redis."""
    monkeypatch.setattr(publication_log, "AsyncSessionLocal", session_factory)
    return redis_client


async def _rows(session: AsyncSession) -> dict[int, Any]:
    """The log for the test workspace, by report id."""
    rows = await ReportPublicationRepository(session).list_for(workspace_id=WORKSPACE)
    return {row.report_id: row for row in rows}


async def test_a_new_report_is_logged_between_the_answer_without_it_and_the_one_with_it(
    logged: Any, db_session: AsyncSession
) -> None:
    """08:00 lists only what we hold; 08:15 names the new week: it arrived in between."""
    await log_first_listings(
        workspace_id=WORKSPACE,
        name="Демо",
        period="weekly",
        listed=[OLD],
        held={OLD_REPORT},
        answered_at=MONDAY_0800,
    )

    await log_first_listings(
        workspace_id=WORKSPACE,
        name="Демо",
        period="weekly",
        listed=[OLD, NEW],
        held={OLD_REPORT},
        answered_at=MONDAY_0815,
    )

    row = (await _rows(db_session))[NEW_REPORT]
    assert (row.prior_list_at, row.first_listed_at) == (MONDAY_0800, MONDAY_0815)
    assert (row.date_from, row.date_to, row.period) == (
        date(2026, 10, 5),
        date(2026, 10, 11),
        "weekly",
    )


async def test_a_later_answer_never_moves_the_first_sighting(
    logged: Any, db_session: AsyncSession
) -> None:
    """Every tick names the report again until it is booked; only the first counts."""
    for answered_at in (MONDAY_0800, MONDAY_0815, MONDAY_0830):
        await log_first_listings(
            workspace_id=WORKSPACE,
            name="Демо",
            period="weekly",
            listed=[NEW] if answered_at > MONDAY_0800 else [],
            held=set(),
            answered_at=answered_at,
        )

    row = (await _rows(db_session))[NEW_REPORT]
    assert row.first_listed_at == MONDAY_0815


async def test_a_report_already_held_is_never_stamped_with_todays_date(
    logged: Any, db_session: AsyncSession
) -> None:
    """A held report was listed before the log existed; writing it now would lie."""
    await log_first_listings(
        workspace_id=WORKSPACE,
        name="Демо",
        period="weekly",
        listed=[OLD],
        held={OLD_REPORT},
        answered_at=MONDAY_0800,
    )

    assert OLD_REPORT not in await _rows(db_session)


async def test_with_no_earlier_answer_the_lower_bound_is_unknown_not_invented(
    logged: Any, db_session: AsyncSession
) -> None:
    """The first answer after a deploy has nothing before it to bound by."""
    await log_first_listings(
        workspace_id=WORKSPACE,
        name="Демо",
        period="weekly",
        listed=[NEW],
        held=set(),
        answered_at=MONDAY_0815,
    )

    assert (await _rows(db_session))[NEW_REPORT].prior_list_at is None
