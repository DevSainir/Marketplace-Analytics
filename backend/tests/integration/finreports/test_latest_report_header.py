"""Which report the P&L's freshness line calls "the newest one on file".

The line's first half is «Последний отчёт WB: 10–16 авг · загружен 18 авг, 06:14»
— the string a seller matches against WB's own отчёты page. Naming the wrong
week there is worse than saying nothing: it is a confident, specific claim that
the statement is current when it is not.

Two ways to get it wrong, and both need real SQL to rule out:

* **Ordering by ingestion time.** A backfill pulls 2024 weeks long after the
  current one, so ``ORDER BY harvested_at`` labels the oldest week as the newest
  publication. The order has to be the settlement period.
* **``NULL`` period headers.** WB has served headers with no stated period, and
  ``NULL`` sorts *first* under a plain ``ORDER BY … DESC`` in PostgreSQL — so
  the page would name a report whose period it cannot print, on a workspace with
  perfectly good weeks on file. ``NULLS LAST`` is a property of the database, not
  of the ORM expression, which is why this test is here rather than in ``unit/``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos import FinancialReportRepository

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ab01")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ab02")

CURRENT_WEEK = 786000000
OLD_WEEK = 700000000
UNDATED = 786999999


def _report(
    report_id: int,
    *,
    date_from: date | None,
    date_to: date | None,
    harvested_at: datetime,
    workspace: uuid.UUID = WORKSPACE,
) -> FinancialReport:
    """One harvested header with an explicit stated period and ingestion time."""
    return FinancialReport(
        report_id=report_id,
        workspace_id=workspace,
        date_from=date_from,
        date_to=date_to,
        currency="KGS",
        harvested_at=harvested_at,
    )


async def _latest(session: AsyncSession, workspace: uuid.UUID = WORKSPACE):
    """What the freshness line would name as the newest report."""
    return await FinancialReportRepository(session).latest_report(workspace_id=workspace)


async def test_the_newest_report_is_the_one_covering_the_latest_week(
    db_session: AsyncSession,
) -> None:
    """The plain case: the most recent settlement period, with its own ingestion time."""
    db_session.add_all(
        [
            _report(
                OLD_WEEK,
                date_from=date(2026, 8, 3),
                date_to=date(2026, 8, 9),
                harvested_at=datetime(2026, 8, 11, 6, 14, tzinfo=UTC),
            ),
            _report(
                CURRENT_WEEK,
                date_from=date(2026, 8, 10),
                date_to=date(2026, 8, 16),
                harvested_at=datetime(2026, 8, 18, 3, 14, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    latest = await _latest(db_session)

    assert latest is not None
    assert latest.report_id == CURRENT_WEEK
    assert (latest.date_from, latest.date_to) == (date(2026, 8, 10), date(2026, 8, 16))
    assert latest.harvested_at == datetime(2026, 8, 18, 3, 14, tzinfo=UTC)


async def test_a_backfill_pulled_later_does_not_become_the_newest_report(
    db_session: AsyncSession,
) -> None:
    """Ordering is by settlement period, never by when we happened to fetch it.

    A backfill of two-year-old weeks runs long after the current one is on file.
    Ordered by ``harvested_at`` the page would announce «Последний отчёт WB:
    5–11 фев 2024» over a statement that actually runs to last week — a claim of
    staleness the seller would have no way to reconcile with WB's own site.
    """
    db_session.add_all(
        [
            _report(
                CURRENT_WEEK,
                date_from=date(2026, 8, 10),
                date_to=date(2026, 8, 16),
                harvested_at=datetime(2026, 8, 18, 3, 14, tzinfo=UTC),
            ),
            _report(
                OLD_WEEK,
                date_from=date(2024, 2, 5),
                date_to=date(2024, 2, 11),
                harvested_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    latest = await _latest(db_session)

    assert latest is not None
    assert latest.report_id == CURRENT_WEEK


async def test_a_header_with_no_stated_period_never_outranks_a_dated_one(
    db_session: AsyncSession,
) -> None:
    """``NULL`` sorts first under a bare ``DESC`` — so it is pushed last explicitly.

    Such a header carries nothing the page could name, so letting it win would
    replace a period the seller can check against WB with a blank, on a
    workspace whose weeks are all present.
    """
    db_session.add_all(
        [
            _report(
                CURRENT_WEEK,
                date_from=date(2026, 8, 10),
                date_to=date(2026, 8, 16),
                harvested_at=datetime(2026, 8, 18, 3, 14, tzinfo=UTC),
            ),
            _report(
                UNDATED,
                date_from=None,
                date_to=None,
                harvested_at=datetime(2026, 8, 19, 3, 14, tzinfo=UTC),
            ),
        ]
    )
    await db_session.flush()

    latest = await _latest(db_session)

    assert latest is not None
    assert latest.report_id == CURRENT_WEEK


async def test_an_undated_header_is_still_served_when_it_is_all_there_is(
    db_session: AsyncSession,
) -> None:
    """Sorted last is not dropped: the workspace HAS been harvested, and says so.

    Returning ``None`` here would render as «отчётов ещё нет» over a statement
    built from that report's rows — the page contradicting its own figures.
    """
    db_session.add(
        _report(
            UNDATED,
            date_from=None,
            date_to=None,
            harvested_at=datetime(2026, 8, 19, 3, 14, tzinfo=UTC),
        )
    )
    await db_session.flush()

    latest = await _latest(db_session)

    assert latest is not None
    assert latest.report_id == UNDATED
    assert (latest.date_from, latest.date_to) == (None, None)


async def test_another_tenants_fresher_report_is_invisible(db_session: AsyncSession) -> None:
    """The freshness line names a settlement week — one tenant's, never another's."""
    db_session.add_all(
        [
            _report(
                OLD_WEEK,
                date_from=date(2026, 8, 3),
                date_to=date(2026, 8, 9),
                harvested_at=datetime(2026, 8, 11, 6, 14, tzinfo=UTC),
            ),
            _report(
                CURRENT_WEEK,
                date_from=date(2026, 8, 10),
                date_to=date(2026, 8, 16),
                harvested_at=datetime(2026, 8, 18, 3, 14, tzinfo=UTC),
                workspace=OTHER_WORKSPACE,
            ),
        ]
    )
    await db_session.flush()

    latest = await _latest(db_session)

    assert latest is not None
    assert latest.report_id == OLD_WEEK


async def test_a_never_harvested_workspace_has_no_newest_report(
    db_session: AsyncSession,
) -> None:
    """Distinguishable from a harvested one, so the page can say «отчётов ещё нет»."""
    assert await _latest(db_session, uuid.uuid4()) is None
