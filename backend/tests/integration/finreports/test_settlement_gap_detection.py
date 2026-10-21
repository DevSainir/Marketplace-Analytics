"""Noticing that a settlement day is missing, which nothing used to do.

Every counter the harvest owns measures what a run DID — rows per source,
sources that failed — and a lost day moves none of them. On 2026-08-31 the walk
succeeded, wrote exactly what it was asked for, and stopped asking about a day WB
had not served yet; all five workspaces lost it and a person found it by reading
WB's own site nine days later.

So the detector keys on **report periods, not rows**. "No settlement rows on day
D" is evidence of nothing — a small workspace's whole weekly report can be a
few dozen rows, and a small seller genuinely has days with no sales. WB's report periods tile the
calendar, so a day inside the harvested range belonging to no report is a report
that is missing.

The hole it could not see until 2026-09-14 is the one at the **end**: a week WB
has published and nobody harvested is not between two reports, it is after the
last one, so a scan bounded by `max(date_to)` reported a sound history while
three workspaces were short the whole of 07.09-13.09. `through` is what puts
that edge inside the range, and it sits a publication grace behind today so the
days WB simply has not formed a report for yet stay quiet.

Real Postgres because the query is `generate_series` over a date range with
`coalesce` on both period endpoints, and both halves of that are database
behaviour rather than Python.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.finreports.models import FinancialReport, LogisticsTransaction
from src.modules.finreports.repos import FinancialReportRepository

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ba01")
OTHER_WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ba02")
SINCE = date(2026, 8, 1)
#: Default scan end, before every fixture below, so `greatest(max(date_to),
#: :through)` leaves the upper bound at the newest report a case holds. The
#: trailing-edge cases pass their own — that edge is the whole subject there.
THROUGH = date(2026, 1, 1)


def _report(
    report_id: int,
    date_from: date | None,
    date_to: date | None,
    *,
    workspace: uuid.UUID = WORKSPACE,
) -> FinancialReport:
    """One harvested header with the period WB stated for it."""
    return FinancialReport(
        report_id=report_id,
        workspace_id=workspace,
        date_from=date_from,
        date_to=date_to,
        currency="KGS",
    )


async def _gaps(
    session: AsyncSession, *, since: date = SINCE, through: date = THROUGH
) -> list[date]:
    """The days the nightly survey would report as uncovered."""
    return await FinancialReportRepository(session).settlement_gap_days(
        workspace_id=WORKSPACE, since=since, through=through
    )


async def test_contiguous_weeks_have_no_gaps(db_session: AsyncSession) -> None:
    """The ordinary history: WB's periods tile the calendar, so nothing is missing."""
    db_session.add_all(
        [
            _report(1, date(2026, 8, 17), date(2026, 8, 23)),
            _report(2, date(2026, 8, 24), date(2026, 8, 30)),
            _report(3, date(2026, 8, 31), date(2026, 9, 6)),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session) == []


async def test_the_day_that_was_lost_is_reported(db_session: AsyncSession) -> None:
    """The incident, reproduced exactly: a one-day report never harvested.

    24-30.08 and 01-06.09 were both on file and both correct. The hole between
    them was the whole of report 983241109, and no counter could see it.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 8, 24), date(2026, 8, 30)),
            _report(2, date(2026, 9, 1), date(2026, 9, 6)),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session) == [date(2026, 8, 31)]


async def test_a_multi_day_hole_is_reported_in_full(db_session: AsyncSession) -> None:
    """A whole missing week reads as its days, so the log can name them."""
    db_session.add_all(
        [
            _report(1, date(2026, 8, 17), date(2026, 8, 23)),
            _report(2, date(2026, 9, 1), date(2026, 9, 6)),
        ]
    )
    await db_session.flush()

    gaps = await _gaps(db_session)

    assert gaps[0] == date(2026, 8, 24)
    assert gaps[-1] == date(2026, 8, 31)
    assert len(gaps) == 8


async def test_a_quiet_seller_with_no_rows_is_not_a_gap(db_session: AsyncSession) -> None:
    """The false positive this detector had to avoid to be worth having.

    A day with no settlement rows is a day nothing sold, which is ordinary and
    permanent for a small account. Keying on rows would have alerted on every
    quiet seller every night until somebody muted it.
    """
    db_session.add(_report(1, date(2026, 8, 24), date(2026, 8, 30)))
    db_session.add(
        LogisticsTransaction(
            rrd_id=1,
            report_id=1,
            workspace_id=WORKSPACE,
            nm_id=0,
            supplier_oper_name="Продажа",
            rr_dt=date(2026, 8, 24),
            currency_name="KGS",
        )
    )
    await db_session.flush()

    assert await _gaps(db_session) == []


async def test_a_hole_entirely_before_the_cutoff_is_not_reported(
    db_session: AsyncSession,
) -> None:
    """A hole the nightly pass cannot reach is not an alarm anybody can act on.

    WB does not serve arbitrarily old windows, so raising an ancient gap every
    night would train people to ignore the one that matters.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 6, 1), date(2026, 6, 7)),
            _report(2, date(2026, 6, 15), date(2026, 6, 21)),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session, since=date(2026, 8, 1)) == []


async def test_a_hole_straddling_the_cutoff_is_reported_from_the_cutoff(
    db_session: AsyncSession,
) -> None:
    """Only the reachable part is raised, because only it can be repaired.

    A long stretch between two reports IS what a missing report looks like, so
    it is reported rather than excused — but trimmed to the window the nightly
    pass can actually walk.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 6, 1), date(2026, 6, 7)),
            _report(2, date(2026, 8, 24), date(2026, 8, 30)),
        ]
    )
    await db_session.flush()

    gaps = await _gaps(db_session, since=date(2026, 8, 1))

    assert gaps[0] == date(2026, 8, 1)
    assert gaps[-1] == date(2026, 8, 23)


async def test_a_half_known_period_covers_the_day_it_does_know(
    db_session: AsyncSession,
) -> None:
    """WB serves headers with one endpoint blank; they must not invent a hole.

    `list_periods` already coalesces per side for the same reason. A report that
    knows only its end covers that day rather than nothing at all.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 8, 24), date(2026, 8, 30)),
            _report(2, None, date(2026, 8, 31)),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session) == []


async def test_another_tenants_reports_do_not_fill_our_hole(
    db_session: AsyncSession,
) -> None:
    """The gap is per seller, and a neighbour's complete history proves nothing.

    This is the direction that would be worst: a tenancy slip here would report
    every workspace as sound because one of them was.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 8, 24), date(2026, 8, 30)),
            _report(2, date(2026, 9, 1), date(2026, 9, 6)),
            _report(3, date(2026, 8, 31), date(2026, 8, 31), workspace=OTHER_WORKSPACE),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session) == [date(2026, 8, 31)]


async def test_a_workspace_with_no_reports_has_no_gaps(db_session: AsyncSession) -> None:
    """Never harvested is not the same as short a day, and must not alert.

    Given a real scan end rather than the default, because that is the case
    where the two became confusable: the scan reaches forward now, so without a
    guard a workspace that signed up this morning reports every day back to the
    cutoff as a hole.
    """
    assert await _gaps(db_session, through=date(2026, 9, 7)) == []


async def test_a_published_week_nobody_harvested_is_reported(db_session: AsyncSession) -> None:
    """The 2026-09-14 hole: at the end of the history, not inside it.

    Watermark 13.09 over coverage ending 06.09, and WB's 07.09-13.09 report
    published into a window the gate would never ask about again. Scanned only up
    to the newest report we hold, the survey called that a sound history and the
    fleet gap count stayed at zero.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 8, 24), date(2026, 8, 30)),
            _report(2, date(2026, 8, 31), date(2026, 9, 6)),
        ]
    )
    await db_session.flush()

    gaps = await _gaps(db_session, through=date(2026, 9, 13))

    assert gaps == [date(2026, 9, 7) + timedelta(days=n) for n in range(7)]


async def test_days_wb_has_not_published_yet_are_not_a_gap(db_session: AsyncSession) -> None:
    """The grace, without which the survey would cry every Monday morning.

    WB forms the weekly report the day after the period ends and serves it later
    still — up to eight days later, measured on report 983241109. A week that has
    only just closed is not a fault of ours.
    """
    db_session.add_all(
        [
            _report(1, date(2026, 8, 24), date(2026, 8, 30)),
            _report(2, date(2026, 8, 31), date(2026, 9, 6)),
        ]
    )
    await db_session.flush()

    assert await _gaps(db_session, through=date(2026, 9, 6)) == []
