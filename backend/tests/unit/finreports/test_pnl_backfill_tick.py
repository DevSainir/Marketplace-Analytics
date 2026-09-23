"""How one tick of the P&L lane fetches — which walk, in what order, how much.

Split from ``test_pnl_backfill_sweeps`` on 2026-09-23, which keeps the question
of when the lane may END. This file has the other half: what a tick that is
owed something actually does about it.

The choice that matters most here is the walk. WB serves the same rows by
report id, one per request, and by period, several reports to a page — measured
at 8 on NEVA and 21 on «Демо». The lane takes the window whenever it is owed
more than one report it has WB's list entry for, and pays for the throughput
with a coarser unit: the window books nothing unless the whole span landed.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.rate_limit.surfaces import BACKGROUND_RESERVE_SECONDS
from src.integrations.wildberries.schemas import WBFinanceReportHeader
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

    monkeypatch.setattr(walk, "walk_settlement_reports", _unpatched)
    monkeypatch.setattr(walk, "walk_settlement_window", _unpatched)


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

    monkeypatch.setattr(walk, "walk_settlement_reports", _walk)
    return asked


def _fetch_window(
    monkeypatch: pytest.MonkeyPatch, *, rows: int = 5000, failed: int = 0
) -> list[Any]:
    """Make the by-period walk answer, and record the spans it was asked for."""
    windows: list[Any] = []

    async def _walk(*, reports: tuple[MissingReport, ...], **_kwargs: Any) -> SettlementWalk:
        windows.append(reports)
        return SettlementWalk(rows=rows, windows_failed=failed, completed_through=None)

    monkeypatch.setattr(walk, "walk_settlement_window", _walk)
    return windows


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
    due = tuple(_report(900 + n, weeks_back=7 + n) for n in range(3))
    _backlog(monkeypatch, due=due, outstanding=3, total=10)
    windows = _fetch_window(monkeypatch)
    monkeypatch.setattr(walk, "REPORTS_PER_TICK", 2)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert [report.report_id for report in windows[0]] == [900, 901], (
        "the oldest of the three was left for the next tick"
    )


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
    due = (
        _report(900, weeks_back=7, listed=False),
        _report(901, weeks_back=8, listed=False),
    )
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
    due = tuple(_report(900 + n, weeks_back=7 + n, listed=False) for n in range(4))
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


async def test_the_lane_records_wb_s_totals_for_the_whole_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This lane is the only caller that ever sees the deep archive's totals.

    The forward harvest lists 45 days, so on «Демо» it can fill 8 of 143
    headers and no more. This one lists the entire history every tick, and the
    list is already in hand — so recording them here costs no WB request and is
    the only way the archive's figures are ever filled in.

    It runs before the walk and regardless of whether anything is missing: a
    lane with nothing left to fetch is exactly the state «Демо» is in, and
    it is the state where the totals are the only thing left to collect.
    """
    recorded: list[tuple[Any, ...]] = []

    async def _record(*, workspace_id: uuid.UUID, listed: Any) -> None:
        recorded.append((workspace_id, tuple(listed)))

    monkeypatch.setattr(walk, "record_wb_totals", _record)
    _backlog(monkeypatch, due=(), outstanding=0, total=3, listed=("h1", "h2", "h3"))
    _fetch(monkeypatch)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.finished, "nothing was owed — the totals are all there was to do"
    assert recorded == [(_tokens().workspace_id, ("h1", "h2", "h3"))]


async def test_several_owed_reports_are_taken_as_one_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the hybrid, and it is worth 8-21x.

    WB serves the same rows by period, several reports to a page — measured at
    8 on NEVA and 21 on «Демо». One report per request turns a seven-request
    history into a 143-request one, which at a request a minute is the
    difference between ten minutes and two and a half hours.
    """
    due = tuple(_report(900 + n, weeks_back=7 + n) for n in range(4))
    _backlog(monkeypatch, due=due, outstanding=4, total=10)
    by_id = _fetch(monkeypatch)
    windows = _fetch_window(monkeypatch)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert by_id == [], "four owed reports were fetched one request at a time"
    assert [report.report_id for report in windows[0]] == [900, 901, 902, 903]
    assert step.done == 10


async def test_the_window_does_not_reserve_and_the_single_report_walk_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window of more than one page cannot run against the reserve.

    `acquire` accumulates its wait across pages, so a second page asked for
    360 s against a 240 s cap and the whole window was discarded with 100 000
    rows already committed (NEVA, 2026-09-23). The reserve buys nothing on that
    bucket either: the harvest and «Обновить» spend `detailed/{id}` and `list`,
    never this one.

    The by-id walk keeps it, because that bucket IS the harvest's.
    """
    seen: dict[str, float] = {}

    async def _window(*, reports: Any, reserve_seconds: float = 0.0, **_k: Any) -> SettlementWalk:
        seen["window"] = reserve_seconds
        return SettlementWalk(rows=1, windows_failed=0, completed_through=None)

    async def _by_id(*, reports: Any, reserve_seconds: float = 0.0, **_k: Any) -> SettlementWalk:
        seen["by_id"] = reserve_seconds
        return SettlementWalk(rows=1, windows_failed=0, completed_through=None)

    monkeypatch.setattr(walk, "walk_settlement_window", _window)
    monkeypatch.setattr(walk, "walk_settlement_reports", _by_id)

    _backlog(
        monkeypatch,
        due=(_report(900, weeks_back=7), _report(901, weeks_back=8)),
        outstanding=2,
        total=10,
    )
    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    _backlog(monkeypatch, due=(_report(902, weeks_back=9),), outstanding=1, total=10)
    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert seen["window"] == 0.0
    assert seen["by_id"] == BACKGROUND_RESERVE_SECONDS


async def test_a_single_owed_report_is_still_taken_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window of one fetches the same rows and gives up atomicity for nothing.

    By id the report is booked the moment it finishes; by window it is booked
    only if the whole span landed. With one report in the span those are the
    same set of rows, so the weaker guarantee buys nothing.
    """
    due = (_report(900, weeks_back=7),)
    _backlog(monkeypatch, due=due, outstanding=1, total=10)
    by_id = _fetch(monkeypatch)
    windows = _fetch_window(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert windows == []
    assert _ids(by_id) == [900]


async def test_a_report_wb_never_listed_is_not_put_in_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window books what it fetched from WB's own list entries.

    A report carrying none cannot be certified by it — it would be fetched and
    then left missing, so the next tick would fetch it again, for ever. By id it
    is at least walked; whether it books is then the header's business.
    """
    due = (_report(900, weeks_back=7, listed=False), _report(901, weeks_back=8, listed=False))
    _backlog(monkeypatch, due=due, outstanding=2, total=10)
    by_id = _fetch(monkeypatch)
    windows = _fetch_window(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert windows == []
    assert _ids(by_id) == [900, 901]


async def test_a_window_that_failed_costs_every_report_in_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window is the unit, so a partial span books none of its reports.

    The bar has to say so rather than claim four reports because four were
    asked for — and the ceiling still moves past them, so they come back on the
    next sweep rather than on the next tick.
    """
    due = tuple(_report(900 + n, weeks_back=7 + n) for n in range(4))
    _backlog(monkeypatch, due=due, outstanding=4, total=10)
    _fetch(monkeypatch)
    _fetch_window(monkeypatch, failed=1)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.done == 6, "none of the four landed, so the six already held is all there is"
    assert step.cursor is not None
    resumed = discovery.parse_cursor(step.cursor)
    assert resumed is not None
    assert resumed[0] < due[-1].date_to, "the ceiling moved past the whole window"


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
