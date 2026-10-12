"""WB's weekly settlement calendar, as the gap survey and the freshness line read it."""

from __future__ import annotations

from datetime import date

import pytest

from src.modules.finreports.services.settlement_calendar import (
    last_due_settlement_day,
    next_formed_period,
    settlement_period_end,
)

pytestmark = pytest.mark.unit


def test_a_week_inside_one_month_ends_on_its_sunday() -> None:
    """05.10-11.10.2026 is one period: report 992915233 says exactly that."""
    period_end = settlement_period_end(date(2026, 10, 5))

    assert period_end == date(2026, 10, 11)


def test_a_week_crossing_a_month_end_is_cut_at_the_month_end() -> None:
    """28.09-30.09 and 01.10-04.10 were two reports (992545862, 992863498), not one week."""
    period_end = settlement_period_end(date(2026, 9, 28))

    assert period_end == date(2026, 9, 30)


def test_the_monday_of_a_week_is_not_due_the_next_monday_morning() -> None:
    """On 12.10 the 05.10-11.10 report exists on WB's site and not yet in the API.

    Counting the grace from the day made the survey log «05.10 no report covers»
    on 12.10 and «28.09» on 05.10 — both before WB served the report that
    covered them. Nothing of that week may be due on its own report's morning.
    """
    through = last_due_settlement_day(today=date(2026, 10, 12), grace_days=7)

    assert through == date(2026, 10, 4)


def test_a_whole_week_becomes_due_once_its_period_is_a_grace_old() -> None:
    """Seven days after the Sunday, every day of that week is the survey's again."""
    through = last_due_settlement_day(today=date(2026, 10, 18), grace_days=7)

    assert through == date(2026, 10, 11)


def test_the_next_report_is_formed_the_morning_after_its_period_ends() -> None:
    """Holding 01.10-04.10 on Monday 12.10, the 05.10-11.10 report is WB's already."""
    formed = next_formed_period(after=date(2026, 10, 4), today=date(2026, 10, 12))

    assert formed == (date(2026, 10, 5), date(2026, 10, 11))


def test_a_period_still_running_has_no_report_to_wait_for() -> None:
    """On Sunday 11.10 the week is not over, so nothing is formed and nothing is late."""
    formed = next_formed_period(after=date(2026, 10, 4), today=date(2026, 10, 11))

    assert formed is None
