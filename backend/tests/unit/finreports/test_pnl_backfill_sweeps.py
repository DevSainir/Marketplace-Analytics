"""When the P&L lane may say «История P&L собрана», and when it may not.

This file replaces ``test_pnl_backfill_roll``, and it exists for the same
reason that one did. NEVA's lane walked the three years that predate its account,
got the answer that correctly concludes that stretch, and reported the history
complete over a 715-day hole — 1033/1033, a green lane, a Telegram message
announcing success, and not one settlement row fetched in thirteen hours. The
chooser was right all along; nothing consulted it before ending the lane.

The machinery is different now — a sweep down a list of report ids rather than a
roll between date spans — but the question a walk gets wrong is the same one, so
these tests drive :func:`advance_pnl` across the boundary rather than testing the
rule in isolation. A unit test of the ending rule cannot fail while the walk
ignores it; a test of the walk can.

The other half is termination. A lane that never finishes is not a stalled
progress bar on this endpoint — it is one request a minute against a surface
that answers with escalating penalty blocks.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.integrations.wildberries.schemas import WBFinanceReportHeader
from src.modules.finreports.tasks.backfill import batch, discovery, walk
from src.modules.finreports.tasks.settlement import MissingReport, SettlementWalk, WindowWalk
from src.modules.workspaces.schemas import WorkspaceTokenBundle

TODAY = date(2026, 9, 23)


def _tokens() -> WorkspaceTokenBundle:
    return WorkspaceTokenBundle(
        workspace_id=uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"),
        name="NEVA",
        finance="a-finance-token",
    )


def _report(report_id: int, weeks_back: int, *, listed: bool = True) -> MissingReport:
    """A report the lane is owed.

    ``listed`` says whether WB's own entry came with it. It decides which walk
    the tick may use: the window books what it fetches from those entries, so a
    report without one can only be taken by id.
    """
    date_to = TODAY - timedelta(days=7 * weeks_back)
    header = (
        WBFinanceReportHeader.model_validate(
            {
                "reportId": report_id,
                "dateFrom": (date_to - timedelta(days=6)).isoformat(),
                "dateTo": date_to.isoformat(),
                "createDate": (date_to + timedelta(days=1)).isoformat(),
            }
        )
        if listed
        else None
    )
    return MissingReport(report_id=report_id, date_to=date_to, header=header)


def _ids(asked: list[Any]) -> list[int]:
    """Report ids in the order WB was actually asked for them."""
    return [report.report_id for batch in asked for report in batch]


@pytest.fixture(autouse=True)
def _no_wb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything outside the decision under test, held still.

    The endpoint is open and the clock does not move; each test says what WB
    listed and what the fetch achieved, and nothing else.
    """
    monkeypatch.setattr(walk, "moscow_today", lambda: TODAY)

    async def _open(_token: str) -> float:
        return 0.0

    monkeypatch.setattr(walk, "_shut_for", _open)

    # Both walks, always. A test that patched only one used to reach the real
    # other — which builds a real rate gate and sleeps out a real minute, so the
    # suite went from 20 s to nearly two.
    async def _unpatched(**_kwargs: Any) -> SettlementWalk:
        raise AssertionError("this test reached a WB walk it did not stub")

    monkeypatch.setattr(batch, "walk_settlement_reports", _unpatched)
    monkeypatch.setattr(batch, "walk_settlement_window", _unpatched)


def _backlog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    due: tuple[MissingReport, ...],
    outstanding: int,
    total: int,
    listed: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    """Make the survey answer with this backlog, and record what it was asked."""
    asked: list[dict[str, Any]] = []

    async def _survey(**kwargs: Any) -> discovery.Backlog:
        asked.append(kwargs)
        return discovery.Backlog(due=due, outstanding=outstanding, total=total, listed=listed)

    monkeypatch.setattr(walk, "survey_backlog", _survey)
    return asked


def _fetch(monkeypatch: pytest.MonkeyPatch, *, rows: int = 500, failed: int = 0) -> list[Any]:
    """Make every fetch answer the same way, and record the batches asked for."""
    asked: list[Any] = []

    async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: Any) -> SettlementWalk:
        asked.append(reports)
        return SettlementWalk(rows=rows, windows_failed=failed, completed_through=None)

    monkeypatch.setattr(batch, "walk_settlement_reports", _walk)
    return asked


def _fetch_window(
    monkeypatch: pytest.MonkeyPatch, *, rows: int = 5000, failed: int = 0
) -> list[Any]:
    """Make the by-period walk answer, and record the spans it was asked for."""
    windows: list[Any] = []

    async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: Any) -> WindowWalk:
        windows.append(reports)
        return WindowWalk(rows=rows, ok=not failed, next_cursor=None)

    monkeypatch.setattr(batch, "walk_settlement_window", _walk)
    return windows


# --------------------------------------------------------------------------- #
# The ending
# --------------------------------------------------------------------------- #
async def test_a_sweep_that_ran_out_of_reach_does_not_end_a_lane_that_is_owed_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEVA's failure, as an assertion.

    The ceiling has passed everything, so this sweep has nothing left to fetch —
    and two reports are still missing. A lane that reports ``finished`` here is
    claiming a hole is filled.
    """
    _backlog(monkeypatch, due=(), outstanding=2, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2024, 1, 1), 1, 5), build_ingestion=object()
    )

    assert not step.finished, "the lane ended itself while WB still had reports it lacks"
    assert step.cursor is not None


async def test_a_sweep_that_achieved_something_goes_round_again_from_the_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry path for a report lost to a timeout or a refused page.

    The ceiling moves past such a report inside its own sweep, so without a
    second pass it would be dropped silently — which is the failure this
    subsystem has had most often and noticed latest.
    """
    _backlog(monkeypatch, due=(), outstanding=2, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2024, 1, 1), 1, 5), build_ingestion=object()
    )

    assert step.cursor is not None
    ceiling, sweep, at_start, _open = discovery.parse_cursor(step.cursor) or (None, 0, 0, None)
    assert ceiling == TODAY, "the new sweep starts at the newest end again"
    assert (sweep, at_start) == (2, 2)


async def test_a_sweep_that_changed_nothing_ends_the_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Termination, and it is not cosmetic.

    What is left after a whole pass that shrank nothing is what WB lists and
    does not serve. Asking again is how a lane becomes a permanent one-request-a-
    minute load on a surface that answers with escalating penalty blocks.
    """
    _backlog(monkeypatch, due=(), outstanding=2, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2024, 1, 1), 2, 2), build_ingestion=object()
    )

    assert step.finished
    assert step.cursor is None
    assert "2" in step.message, "the seller is told what is missing, not just that it is over"
    assert "Wildberries" not in step.message, (
        "a backlog that did not shrink is a walk that finished nothing — it is no "
        "evidence at all about what WB will serve"
    )


async def test_a_lane_owed_nothing_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary ending. A lane that never finishes is a leak."""
    _backlog(monkeypatch, due=(), outstanding=0, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2024, 1, 1), 1, 5), build_ingestion=object()
    )

    assert step.finished
    assert (step.done, step.total) == (10, 10)
