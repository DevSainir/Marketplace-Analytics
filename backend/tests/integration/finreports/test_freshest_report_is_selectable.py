"""The newest harvested report has to reach the period picker, not just the DB.

Two backend figures decide whether a freshly harvested week is *visible*, and
they are computed by two different queries over the same table:

* ``latest_settled_date`` — ``max(date_to)`` — is what ``GET /harvest/state``
  returns as ``latest_settled``. The SPA compares it against the day already on
  screen; a change is the whole basis of «Загружен отчёт по …» and of the
  reload that follows it (``useHarvestRefresh``).
* ``list_periods`` — every report with a resolved period — is what ``GET /weeks``
  serves, and the picker's whole span is built from it (``fullSpan`` in the
  finreports store).

If the first reaches a day the second does not, the UI announces a report it
then cannot show: the notice names the new settlement day, the picker never
offers it, and — because the harvest's freshness gate probes the days *after*
``latest_settled`` — the next tick concludes there is nothing new and the report
stays invisible for good. That failure is silent on every metric: the rows were
written, the task succeeded, the counters moved.

So the invariant these tests pin is a relationship, not a value: **the day the
service reports as settled is always a day the period list actually reaches.**
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport
from src.modules.finreports.repos import FinancialReportRepository

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000fe51")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-000000000a11")

LAST_WEEK = 785000000
THIS_WEEK = 969371534


def _report(report_id: int, *, date_from: date | None, date_to: date | None, workspace=WORKSPACE):
    """One harvested report header with the given stated period."""
    return FinancialReport(
        report_id=report_id,
        workspace_id=workspace,
        date_from=date_from,
        date_to=date_to,
        currency="KGS",
    )


async def _weeks(session: AsyncSession) -> list[tuple[int, date, date]]:
    """The periods the picker would be built from."""
    return await FinancialReportRepository(session).list_periods(workspace_id=WORKSPACE)


async def _settled(session: AsyncSession) -> date | None:
    """The day «Обновить» would report as the latest settled one."""
    return await FinancialReportRepository(session).latest_settled_date(workspace_id=WORKSPACE)


async def test_the_freshest_report_is_the_first_period_the_picker_offers(
    db_session: AsyncSession,
) -> None:
    """A newly harvested week leads the period list and matches the settled day.

    The plain success case, asserted as the relationship rather than as two
    values: whatever «Обновить» calls the latest settled day must be the day the
    first week in the picker ends on, or the seller is told about a week the
    picker cannot select.
    """
    db_session.add_all(
        [
            _report(LAST_WEEK, date_from=date(2026, 7, 6), date_to=date(2026, 7, 12)),
            _report(THIS_WEEK, date_from=date(2026, 7, 13), date_to=date(2026, 7, 19)),
        ]
    )
    await db_session.flush()

    weeks = await _weeks(db_session)
    settled = await _settled(db_session)

    assert weeks[0] == (THIS_WEEK, date(2026, 7, 13), date(2026, 7, 19))
    assert settled == weeks[0][2]


async def test_a_report_with_no_stated_start_still_reaches_the_picker(
    db_session: AsyncSession,
) -> None:
    """A report WB gave an end but no start for is announced AND selectable.

    Reachable, not hypothetical: the header period is
    ``stated_from or rr_dt`` per row (``ingestion/rows.py``), so a report whose
    rows carry a settlement end but leave both the stated start and ``rr_dt``
    blank lands with ``date_from IS NULL`` and ``date_to`` set. ``max(date_to)``
    counts that report; ``list_periods`` filters it out. The seller is then told
    «Загружен отчёт по 2026-07-19» over a picker that stops a week earlier, and
    the freshness gate — probing from 2026-07-20 — never asks for it again.
    """
    db_session.add_all(
        [
            _report(LAST_WEEK, date_from=date(2026, 7, 6), date_to=date(2026, 7, 12)),
            _report(THIS_WEEK, date_from=None, date_to=date(2026, 7, 19)),
        ]
    )
    await db_session.flush()

    weeks = await _weeks(db_session)
    settled = await _settled(db_session)

    assert settled is not None
    assert max(week[2] for week in weeks) == settled


async def test_another_tenants_fresher_report_moves_neither_figure(
    db_session: AsyncSession,
) -> None:
    """Both queries are workspace-scoped, so a neighbour's week is invisible.

    The two figures agreeing is worth nothing if they agree on another tenant's
    data — and this is the pair a tenancy slip would corrupt together, which is
    exactly the shape the invariant above cannot catch on its own.
    """
    db_session.add_all(
        [
            _report(LAST_WEEK, date_from=date(2026, 7, 6), date_to=date(2026, 7, 12)),
            _report(
                THIS_WEEK,
                date_from=date(2026, 7, 13),
                date_to=date(2026, 7, 19),
                workspace=OTHER_WORKSPACE,
            ),
        ]
    )
    await db_session.flush()

    weeks = await _weeks(db_session)
    settled = await _settled(db_session)

    assert [week[0] for week in weeks] == [LAST_WEEK]
    assert settled == date(2026, 7, 12)
