"""What the P&L lane decides to ask WB for, now that WB names the reports.

This file replaces ``test_pnl_backfill_cursor``, whose subject no longer exists.
That one pinned :func:`next_span` — a heuristic that read the shape of a
seller's stored settlement days and guessed where a hole was, with a fourteen-day
tolerance to tell an ordinary quiet week from a real gap. It guessed wrong in
production twice, and both times the lane declared the history complete over the
hole it could not see.

There is nothing left to guess. WB lists its reports, we hold a set of ids, and
the backlog is the difference — so what is worth pinning here is not "does the
finder find holes" but the three things the difference is taken against: the
depth, the boundary with the forward harvest, and the ceiling that makes a
sweep terminate.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import date, timedelta
from typing import Any

import pytest

from src.integrations.wildberries.schemas.finance import WBFinanceReportHeader
from src.modules.finreports.constants import SETTLEMENT_LIST_WINDOW_DAYS
from src.modules.finreports.tasks.backfill import discovery
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.schemas import WorkspaceTokenBundle

TODAY = date(2026, 9, 23)

#: Deep enough to hold the whole of the fixture history below.
FLOOR = TODAY - timedelta(days=5 * 365)

#: The oldest day the forward harvest lists. Its window is inclusive, so the
#: backfill's own newest report is the day BEFORE this — the two lanes meeting
#: exactly here, with neither a gap nor an overlap, is what this file checks.
HORIZON = TODAY - timedelta(days=SETTLEMENT_LIST_WINDOW_DAYS)

#: The newest report the backfill may take.
NEWEST = HORIZON - timedelta(days=1)


def _tokens() -> WorkspaceTokenBundle:
    return WorkspaceTokenBundle(
        workspace_id=uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"),
        name="NEVA",
        finance="a-finance-token",
    )


def _header(report_id: int, date_to: date) -> WBFinanceReportHeader:
    """One weekly report header, in WB's own payload shape."""
    return WBFinanceReportHeader.model_validate(
        {
            "reportId": report_id,
            "dateFrom": (date_to - timedelta(days=6)).isoformat(),
            "dateTo": date_to.isoformat(),
            "createDate": (date_to + timedelta(days=1)).isoformat(),
            "reportType": 1,
        }
    )


def _wb_lists(
    monkeypatch: pytest.MonkeyPatch, headers: list[WBFinanceReportHeader]
) -> list[tuple[date, date]]:
    """Make WB answer the list with these headers, and record what it was asked.

    Returns the list of ``(date_from, date_to)`` windows requested, so a test
    can assert on the question as well as on the answer.
    """
    asked: list[tuple[date, date]] = []

    class _Client:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def list_reports(
            self, *, date_from: date, date_to: date, **_kwargs: Any
        ) -> list[WBFinanceReportHeader]:
            asked.append((date_from, date_to))
            return headers

    monkeypatch.setattr(discovery, "WBFinanceReportsClient", _Client)
    return asked


def _we_hold(monkeypatch: pytest.MonkeyPatch, ids: Collection[int]) -> None:
    """Make the settlement tables answer with exactly these report ids."""

    async def _held(_workspace_id: uuid.UUID, *, since: date) -> Collection[int]:
        return set(ids)

    monkeypatch.setattr(discovery, "held_report_ids", _held)


# --------------------------------------------------------------------------- #
# What the backlog is
# --------------------------------------------------------------------------- #
async def test_a_hole_in_the_middle_of_the_history_is_an_id_like_any_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEVA's bug, restated in the unit that replaced the one that had it.

    Its history was 51 days of rows spanning two years with a 715-day hole in
    the middle, and the span heuristic could not see it. A set difference has no
    middle: the id is either held or it is not.
    """
    listed = [_header(100 + n, NEWEST - timedelta(days=7 * n)) for n in range(6)]
    _wb_lists(monkeypatch, listed)
    _we_hold(monkeypatch, {100, 101, 104, 105})

    backlog = await discovery.survey_backlog(
        tokens=_tokens(), floor=FLOOR, ceiling=TODAY, today=TODAY
    )

    assert [report.report_id for report in backlog.due] == [102, 103]
    assert backlog.outstanding == 2
    assert backlog.total == 6
    assert backlog.done == 4


async def test_the_backlog_is_offered_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backfill is interrupted far more often than it is finished.

    What a seller needs from an interrupted one is this month's P&L, not the
    archive. Walking the other way, NEVA was stopped holding 248 days of 2024 and
    nothing at all from the summer.
    """
    listed = [_header(100 + n, NEWEST - timedelta(days=7 * n)) for n in range(4)]
    _wb_lists(monkeypatch, listed)
    _we_hold(monkeypatch, set())

    backlog = await discovery.survey_backlog(
        tokens=_tokens(), floor=FLOOR, ceiling=TODAY, today=TODAY
    )

    assert [report.date_to for report in backlog.due] == sorted(
        (report.date_to for report in backlog.due), reverse=True
    )
    assert backlog.due[0].report_id == 100


async def test_the_reports_the_forward_harvest_owns_are_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two lanes meet at the harvest's list window and must not overlap.

    The harvest walks everything inside it on a quarter-hourly tick. A backfill
    reaching in would spend a minute-long token racing it for rows that were
    arriving anyway — and both would be writing the same weeks from opposite
    ends, which is the shape the old lane's «days after the newest stored row»
    rule existed to avoid.
    """
    recent = _header(200, HORIZON)
    older = _header(201, NEWEST)
    _wb_lists(monkeypatch, [recent, older])
    _we_hold(monkeypatch, set())

    backlog = await discovery.survey_backlog(
        tokens=_tokens(), floor=FLOOR, ceiling=TODAY, today=TODAY
    )

    assert [report.report_id for report in backlog.due] == [201]
    assert backlog.total == 1, "a report the harvest owns is not this lane's denominator either"


async def test_reports_older_than_the_floor_are_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor is a parameter so a test can narrow history; it must bite.

    Production passes `WB_REPORTS_EPOCH` and collects everything — see
    `test_pnl_backfill_sweeps` for that half. This pins that the bound is real,
    so a future depth decision has something to land on rather than a parameter
    nothing reads.
    """
    inside = _header(300, FLOOR + timedelta(days=1))
    outside = _header(301, FLOOR - timedelta(days=1))
    _wb_lists(monkeypatch, [inside, outside])
    _we_hold(monkeypatch, set())

    backlog = await discovery.survey_backlog(
        tokens=_tokens(), floor=FLOOR, ceiling=TODAY, today=TODAY
    )

    assert [report.report_id for report in backlog.due] == [300]


async def test_the_ceiling_hides_reports_this_sweep_has_already_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``due`` is what this tick may fetch; ``outstanding`` is what is owed.

    The two differ precisely by what the ceiling has passed, and keeping them
    apart is what lets the sweep rule ask «did the whole pass achieve anything»
    rather than «is there anything below me».
    """
    newer = _header(400, NEWEST - timedelta(days=7))
    older = _header(401, NEWEST - timedelta(days=14))
    _wb_lists(monkeypatch, [newer, older])
    _we_hold(monkeypatch, set())

    backlog = await discovery.survey_backlog(
        tokens=_tokens(), floor=FLOOR, ceiling=older.date_to, today=TODAY
    )

    assert [report.report_id for report in backlog.due] == [401]
    assert backlog.outstanding == 2


async def test_the_whole_depth_is_listed_in_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Measured on «Демо» 2026-09-23: 143 reports for a 1095-day window.

    Discovery being one request is what makes re-asking every tick affordable,
    and re-asking every tick is what keeps the lane from carrying a second,
    staler copy of the truth. A survey that paged would quietly reintroduce it.
    """
    asked = _wb_lists(monkeypatch, [])
    _we_hold(monkeypatch, set())

    await discovery.survey_backlog(tokens=_tokens(), floor=FLOOR, ceiling=TODAY, today=TODAY)

    assert asked == [(FLOOR, TODAY)]


# --------------------------------------------------------------------------- #
# The ceiling
# --------------------------------------------------------------------------- #
def test_the_ceiling_moves_below_the_oldest_report_attempted() -> None:
    """Otherwise a report WB lists and serves no rows for is asked for for ever.

    Headers are derived from rows, so such a report never lands in
    ``financial_report`` and never stops being missing. On a 1/min endpoint that
    answers with penalty blocks, an unbounded retry is not a slow lane.
    """
    attempted = (
        MissingReport(report_id=1, date_to=date(2026, 8, 30)),
        MissingReport(report_id=2, date_to=date(2026, 8, 23)),
    )

    moved = discovery.advance_ceiling(attempted, ceiling=TODAY)

    assert moved == date(2026, 8, 22)


def test_a_tick_that_attempted_nothing_leaves_the_ceiling_where_it_was() -> None:
    """A tick refused a token has learned nothing about the history's shape."""
    assert discovery.advance_ceiling((), ceiling=TODAY) == TODAY


# --------------------------------------------------------------------------- #
# The cursor
# --------------------------------------------------------------------------- #
def test_the_cursor_survives_a_round_trip() -> None:
    """It crosses a database, a deploy and a worker recreate between ticks."""
    written = discovery.format_cursor(date(2026, 7, 1), 2, 17)

    assert discovery.parse_cursor(written) == (date(2026, 7, 1), 2, 17, None)


def test_the_cursor_this_rewrite_replaced_is_rejected_rather_than_misread() -> None:
    """``span_from|span_to|rrd_id|empties|search`` also starts with a date.

    Read as this lane's cursor it would take an ``rrd_id`` for a backlog count
    and hand the sweep rule a denominator in the millions. Rejecting it costs a
    lane mid-walk one restart from the top, which is minutes.
    """
    assert discovery.parse_cursor("2026-07-01|2026-07-31|4242|0|2026-08-01") is None


def test_an_unreadable_cursor_starts_a_fresh_sweep_instead_of_raising() -> None:
    """A parser that raises on an unexpected string turns a deploy into a
    permanently failing tick, which is how this lane has been lost before."""
    assert discovery.parse_cursor("nonsense") is None
