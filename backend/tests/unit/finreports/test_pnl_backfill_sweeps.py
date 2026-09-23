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

from src.core.exceptions import IntegrationError
from src.modules.finreports.tasks.backfill import discovery, walk
from src.modules.finreports.tasks.settlement import MissingReport, SettlementWalk
from src.modules.workspaces.schemas import WorkspaceTokenBundle

TODAY = date(2026, 9, 23)


def _tokens() -> WorkspaceTokenBundle:
    return WorkspaceTokenBundle(
        workspace_id=uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"),
        name="NEVA",
        finance="a-finance-token",
    )


def _report(report_id: int, weeks_back: int) -> MissingReport:
    return MissingReport(report_id=report_id, date_to=TODAY - timedelta(days=7 * weeks_back))


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


def _backlog(
    monkeypatch: pytest.MonkeyPatch, *, due: tuple[MissingReport, ...], outstanding: int, total: int
) -> list[dict[str, Any]]:
    """Make the survey answer with this backlog, and record what it was asked."""
    asked: list[dict[str, Any]] = []

    async def _survey(**kwargs: Any) -> discovery.Backlog:
        asked.append(kwargs)
        return discovery.Backlog(due=due, outstanding=outstanding, total=total)

    monkeypatch.setattr(walk, "survey_backlog", _survey)
    return asked


def _fetch(monkeypatch: pytest.MonkeyPatch, *, rows: int = 500, failed: int = 0) -> list[Any]:
    """Make every fetch answer the same way, and record the batches asked for."""
    asked: list[Any] = []

    async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: Any) -> SettlementWalk:
        asked.append(reports)
        return SettlementWalk(rows=rows, windows_failed=failed, completed_through=None)

    monkeypatch.setattr(walk, "walk_settlement_reports", _walk)
    return asked


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
    ceiling, sweep, at_start = discovery.parse_cursor(step.cursor) or (None, 0, 0)
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


async def test_a_lane_owed_nothing_finishes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary ending. A lane that never finishes is a leak."""
    _backlog(monkeypatch, due=(), outstanding=0, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2024, 1, 1), 1, 5), build_ingestion=object()
    )

    assert step.finished
    assert (step.done, step.total) == (10, 10)


# --------------------------------------------------------------------------- #
# What a working tick does
# --------------------------------------------------------------------------- #
async def test_the_lane_asks_wb_for_the_whole_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no depth limit, and that is a measurement rather than a taste.

    Three months was what a new seller got when the old endpoint served roughly
    one page an hour and three months of a large seller's detail was ~15 h of
    walking. It is now one request per report at one request a minute, and a
    seller forms about 52 reports a year whatever their size — so a full
    history is ~52 minutes per year of trading, against an advertising lane
    that takes ~7 h on the same signup. Nothing is left for a floor to buy.
    """
    asked = _backlog(monkeypatch, due=(), outstanding=0, total=0)
    _fetch(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert asked[0]["floor"] == discovery.WB_REPORTS_EPOCH


async def test_a_tick_takes_the_newest_reports_when_it_cannot_take_them_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signup is the case that matters, and only the direction decides whether a
    seller's first settlement rows are this month's or two years ago's."""
    due = (_report(900, weeks_back=7), _report(901, weeks_back=8), _report(902, weeks_back=9))
    _backlog(monkeypatch, due=due, outstanding=3, total=10)
    asked = _fetch(monkeypatch)
    monkeypatch.setattr(walk, "REPORTS_PER_TICK", 2)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert _ids(asked) == [900, 901], "the oldest of the three was left for the next tick"


async def test_a_tick_walks_several_reports_rather_than_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole of the throughput, and it is not a micro-optimisation.

    A tick's countdown is read from a bucket the tick has just emptied, with the
    background reserve on top, so one report per tick costs about three minutes
    per report against a budget that allows one. Batching spends the waiting on
    the next report instead of on nothing.
    """
    due = tuple(_report(900 + n, weeks_back=7 + n) for n in range(5))
    _backlog(monkeypatch, due=due, outstanding=5, total=10)
    asked = _fetch(monkeypatch)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert len(_ids(asked)) == 5
    assert step.done == 10


async def test_the_reports_are_handed_over_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What lets the tick walk newest first at all.

    ``walk_settlement_reports`` certifies the unbroken PREFIX of what it is
    handed, so a descending batch passed whole would certify a gap in front of
    itself — the old lane sorted a batch ascending for exactly that reason, and
    paid for it by leaving a seller the archive when a tick was cut short. One
    report per call makes the prefix rule trivially true and gives the direction
    back.
    """
    due = (_report(900, weeks_back=7), _report(901, weeks_back=8))
    _backlog(monkeypatch, due=due, outstanding=2, total=10)
    asked = _fetch(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert [len(batch) for batch in asked] == [1, 1]
    assert _ids(asked) == [900, 901], "newest first, which is the order it was offered in"


async def test_a_tick_out_of_time_stops_between_reports_and_leaves_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running past the task's soft limit is not a slow tick but a silent one.

    `SoftTimeLimitExceeded` is not the error the lane catches, so a tick that
    overran would record nothing and re-enqueue nothing. The reports it did not
    reach must stay above the ceiling, or they are lost rather than deferred.
    """
    due = tuple(_report(900 + n, weeks_back=7 + n) for n in range(4))
    _backlog(monkeypatch, due=due, outstanding=4, total=10)
    asked = _fetch(monkeypatch)
    monkeypatch.setattr(walk, "_TICK_WORK_BUDGET_SECONDS", -1.0)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert _ids(asked) == [900], "one report is always attempted; a tick that does nothing spins"
    assert step.cursor is not None
    resumed = discovery.parse_cursor(step.cursor)
    assert resumed is not None
    assert resumed[0] >= due[1].date_to, "the reports it never reached are still offered"


async def test_the_ceiling_drops_below_what_this_tick_attempted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise a report WB serves no rows for is asked for once a minute for
    ever: no rows means no header, and no header means it stays missing."""
    due = (_report(900, weeks_back=7),)
    _backlog(monkeypatch, due=due, outstanding=1, total=10)
    _fetch(monkeypatch, rows=0)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.cursor is not None
    resumed = discovery.parse_cursor(step.cursor)
    assert resumed is not None
    assert resumed[0] < due[0].date_to


async def test_a_report_that_failed_is_not_counted_as_collected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bar has to mean what it says — it is the only thing a seller waiting
    on their first P&L can read."""
    due = (_report(900, weeks_back=7),)
    _backlog(monkeypatch, due=due, outstanding=1, total=10)
    _fetch(monkeypatch, failed=1)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.done == 9, "nine held before the tick, and the tenth did not arrive"


async def test_the_opening_backlog_is_recorded_on_the_first_tick_of_a_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep rule compares against it, so a sweep that never recorded one
    could not tell «this pass achieved something» from «it achieved nothing»."""
    due = (_report(900, weeks_back=7),)
    _backlog(monkeypatch, due=due, outstanding=4, total=10)
    _fetch(monkeypatch)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.cursor is not None
    assert (discovery.parse_cursor(step.cursor) or (None, 0, 0))[2] == 4


# --------------------------------------------------------------------------- #
# What a tick does instead of asking
# --------------------------------------------------------------------------- #
async def test_a_standing_block_re_enqueues_without_spending_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read before anything is sent, and that is the point.

    ``acquire`` sleeps up to 1000 s before it raises, which outlasts this task's
    own soft limit — and ``SoftTimeLimitExceeded`` is not the error the lane
    catches, so the tick would die recording nothing and re-enqueueing nothing.
    That is how this lane was lost for eleven hours on 2026-09-10.
    """

    async def _shut(_token: str) -> float:
        return 2762.0

    monkeypatch.setattr(walk, "_shut_for", _shut)

    async def _never(**_kwargs: Any) -> discovery.Backlog:
        raise AssertionError("the tick asked WB while it was blocked")

    monkeypatch.setattr(walk, "survey_backlog", _never)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2026, 7, 1), 2, 5), build_ingestion=object()
    )

    assert not step.finished
    assert step.done is None, "a blocked tick learned nothing; the bar must not move"
    assert step.cursor == discovery.format_cursor(date(2026, 7, 1), 2, 5)


async def test_a_refused_list_leaves_the_progress_bar_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A denominator of zero means «I learned nothing», not «there is nothing».

    The caller reads it that way and leaves the stored estimate in place;
    writing a 0 through would empty a bar that is mid-walk and then jump it
    back, which reads as the walk having restarted.
    """

    async def _fails(**_kwargs: Any) -> discovery.Backlog:
        raise IntegrationError("WildBerries did not answer")

    monkeypatch.setattr(walk, "survey_backlog", _fails)

    step = await walk.advance_pnl(
        _tokens(), cursor=discovery.format_cursor(date(2026, 7, 1), 2, 5), build_ingestion=object()
    )

    assert not step.finished
    assert (step.done, step.total) == (None, 0)
    assert step.cursor == discovery.format_cursor(date(2026, 7, 1), 2, 5)


async def test_a_workspace_with_no_finance_token_ends_rather_than_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing was asked and nothing can be, so the lane must not sit RUNNING
    for ever waiting for a request it will never make."""
    step = await walk.advance_pnl(
        WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="Без токена"),
        cursor=None,
        build_ingestion=object(),
    )

    assert step.finished
    assert step.cursor is None
