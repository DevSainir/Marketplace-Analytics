"""What the post-deploy smoke probe asks the P&L for, and what it tells the deploy.

The pages themselves are opened on real rows in
``tests/integration/monitoring/test_smoke_after_deploy.py``. Here are the two
pure decisions around them: which window the P&L report is opened on, and which
exit code a run's findings turn into — the one number the deploy reads.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.smoke import SmokeReport
from scripts.smoke.finreports import default_window
from scripts.smoke_after_deploy import EXIT_BROKEN, EXIT_CANNOT_CHECK, verdict
from src.modules.finreports.schemas import WeekPeriod, WeeksResponse

pytestmark = pytest.mark.unit


def test_the_p_and_l_opens_on_the_last_seven_days_the_daily_tail_included() -> None:
    """The window ends on the newest settled day, the daily tail's when it runs past the weeks.

    That is the window ``PnlView`` opens on a first visit (``presetWindow``), so
    the probe opens the report a seller opens rather than a neighbouring one.
    """
    weeks = WeeksResponse(
        weeks=[
            WeekPeriod(report_id=2, date_from=date(2026, 9, 7), date_to=date(2026, 9, 13)),
            WeekPeriod(report_id=1, date_from=date(2026, 8, 31), date_to=date(2026, 9, 6)),
        ],
        provisional_through=date(2026, 9, 16),
    )

    assert default_window(weeks) == (date(2026, 9, 10), date(2026, 9, 16))


def test_a_history_shorter_than_a_week_opens_on_all_of_it() -> None:
    """The seven days are held inside the history, as the page's preset is."""
    weeks = WeeksResponse(
        weeks=[WeekPeriod(report_id=1, date_from=date(2026, 9, 10), date_to=date(2026, 9, 13))]
    )

    assert default_window(weeks) == (date(2026, 9, 10), date(2026, 9, 13))


def test_a_skipped_page_is_printed_and_does_not_fail_the_deploy(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stale settlement rollup is the ordinary state after a harvest, not a broken release.

    But it must be SAID: a page that was not opened may not read as one that passed.
    """
    report = SmokeReport(
        cards=[1], rendered={"cards": 1}, skipped=["P&L report: the rollup is behind"]
    )

    code = verdict(report)

    assert code == 0
    assert "smoke: skipped P&L report: the rollup is behind" in capsys.readouterr().out


def test_one_broken_page_fails_the_deploy_whatever_else_rendered() -> None:
    """Every other page opening is no excuse: one 500 is a page a seller cannot use."""
    report = SmokeReport(
        cards=[1], rendered={"cards": 1, "heatmap": 3}, failures=["A/Б list: ValueError: x"]
    )

    assert verdict(report) == EXIT_BROKEN


def test_no_card_to_open_is_not_a_pass_even_when_other_pages_rendered() -> None:
    """The cards are what the probe exists for; not finding any is "not checked", exit 3."""
    report = SmokeReport(cards=[], rendered={"monitoring list": 0, "A/Б list": 2})

    assert verdict(report) == EXIT_CANNOT_CHECK
