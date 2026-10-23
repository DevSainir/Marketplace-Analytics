"""A scheduled tick asks WB only about sellers still owed a report today.

What a day can bring is known in advance: the daily report for yesterday, and a
weekly report once a period has closed on a Sunday or a month end. The rule that
turns that into «is anything left to come» decides whether a tick spends two
`list` requests per seller, so both halves are pinned — the calendar, and the
fleet actually skipping the seller it clears.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from src.modules.finreports.tasks.harvest import fleet
from src.modules.finreports.tasks.harvest.due import last_period_end, owes_a_report
from src.modules.finreports.tasks.harvest.fleet import harvest_all_workspaces
from src.modules.workspaces.contract import WorkspaceTokenBundle
from tests.support.fakes import FakeRedis

pytestmark = pytest.mark.unit

TUESDAY = date(2026, 9, 22)
MONDAY = date(2026, 9, 21)
SUNDAY = date(2026, 9, 20)
LAST_SUNDAY = date(2026, 9, 13)


def test_a_period_closes_on_a_sunday() -> None:
    """From Wednesday back to the Sunday before it."""
    assert last_period_end(date(2026, 9, 23)) == SUNDAY


def test_a_period_also_closes_on_a_month_end() -> None:
    """A week straddling two months is two reports; the first ends on the 30th.

    30.09.2026 is a Wednesday, so the Sunday rule alone would say the 27th.
    """
    assert last_period_end(date(2026, 10, 1)) == date(2026, 9, 30)


def test_nothing_is_owed_once_yesterday_and_the_last_week_are_held() -> None:
    """Weekly through Sunday, daily through Monday: a Tuesday has nothing left."""
    assert not owes_a_report(today=TUESDAY, settled_through=SUNDAY, tail_through=MONDAY)


def test_yesterday_s_daily_report_is_owed_until_it_arrives() -> None:
    """The daily report for Monday is still to come on Tuesday's night ticks."""
    assert owes_a_report(today=TUESDAY, settled_through=SUNDAY, tail_through=SUNDAY)


def test_the_weekly_report_is_owed_even_when_the_daily_ones_cover_the_days() -> None:
    """On a Monday the daily tail already reaches Sunday; the settlement does not.

    The daily rows are provisional — the weekly report is the document — so a
    tail reaching yesterday must not stand in for it.
    """
    assert owes_a_report(today=MONDAY, settled_through=LAST_SUNDAY, tail_through=SUNDAY)


def test_a_weekly_report_served_late_stays_owed_on_the_days_after() -> None:
    """Missing on Monday, still asked for on Tuesday — not left for next week."""
    assert owes_a_report(today=TUESDAY, settled_through=LAST_SUNDAY, tail_through=MONDAY)


def test_a_seller_with_nothing_on_file_is_always_owed() -> None:
    """No weekly report at all: there is no calendar to trust yet."""
    assert owes_a_report(today=TUESDAY, settled_through=None, tail_through=None)


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SUNDAY


class _FakeReportRepo:
    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date:
        return SUNDAY

    async def report_ids_since(self, *, workspace_id: uuid.UUID, since: date) -> set[int]:
        return set()


HOLDS_ALL = uuid.UUID("019f657a-0000-7000-8000-000000000001")
WAITING = uuid.UUID("019f657a-0000-7000-8000-000000000002")


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """A fleet of two, one of them owed a report; record whom WB is asked about."""
    calls: list[uuid.UUID] = []
    redis = FakeRedis()
    bundles = [
        WorkspaceTokenBundle(workspace_id=ws, name=str(ws), statistics="s", finance="f")
        for ws in (HOLDS_ALL, WAITING)
    ]

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return bundles

    async def _nothing(*_args: object, **_kwargs: object) -> dict[Any, Any]:
        return {}

    async def _no_repairs(*_args: object, **_kwargs: object) -> set[uuid.UUID]:
        return set()

    async def _owed(ids: list[uuid.UUID], *, today: date) -> set[uuid.UUID]:
        return {WAITING} & set(ids)

    async def _check(*, tokens: WorkspaceTokenBundle, **_kwargs: object) -> tuple[Any, ...]:
        calls.append(tokens.workspace_id)
        return None, (), []

    async def _blocked(*_args: object) -> float:
        return 0.0

    async def _totals(**_kwargs: object) -> None:
        return None

    async def _tail(**_kwargs: object) -> dict[str, int]:
        return {"reports": 0, "rows": 0, "reports_failed": 0}

    monkeypatch.setattr(fleet, "get_redis", lambda: redis)
    monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(fleet, "survey_settlement_gaps", _nothing)
    monkeypatch.setattr(fleet, "gap_repair_due", _no_repairs)
    monkeypatch.setattr(fleet, "sellers_owed_a_report", _owed)
    monkeypatch.setattr(fleet, "check_freshness", _check)
    monkeypatch.setattr(fleet, "settlement_blocked_for", _blocked)
    monkeypatch.setattr(fleet, "record_wb_totals", _totals)
    monkeypatch.setattr(fleet, "tail_one_workspace", _tail)
    monkeypatch.setattr(fleet, "freshness_record_store", lambda: None)
    monkeypatch.setattr(fleet, "moscow_today", lambda: TUESDAY)
    return calls


async def test_a_gated_tick_asks_only_about_the_seller_still_owed(
    asked: list[uuid.UUID],
) -> None:
    """The seller holding everything costs no request; the other is asked."""
    totals = await harvest_all_workspaces(gated=True)

    assert asked == [WAITING]
    assert totals["workspaces_skipped"] >= 1


async def test_an_ungated_run_asks_about_everybody(asked: list[uuid.UUID]) -> None:
    """The "Refresh" button and the nightly pass do not consult the calendar."""
    await harvest_all_workspaces()

    assert sorted(asked) == sorted([HOLDS_ALL, WAITING])
