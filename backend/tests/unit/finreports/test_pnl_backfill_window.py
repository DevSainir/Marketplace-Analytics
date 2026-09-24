"""Which walk one tick chooses, and over what span.

WB serves the same rows two ways, and the lane picks per tick. By report id it
is one request each and a report books the moment it finishes; by period it is
several reports to a page — 8 on NEVA, 21 on «Демо» — and the unit becomes
the span, which books nothing unless the whole of it landed.

The rule that took two production failures to find: a window may only ever span
a RUN of owed reports, consecutive in WB's own ordering with nothing held in
between. A window fetches every row in its span, so twelve scattered reports
span most of a seller's history — and the extra is not bandwidth but pages,
which are the thing WB rates.
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
    listed: tuple[Any, ...] | None = None,
) -> list[dict[str, Any]]:
    """Make the survey answer with this backlog, and record what it was asked.

    ``listed`` defaults to exactly the owed reports, which is the CONTIGUOUS
    case: nothing held sits between them, so the tick may span them in one
    window. Pass it explicitly to put a held report in the middle and get the
    scattered case instead.
    """
    if listed is None:
        listed = tuple(report.header for report in due if report.header is not None)
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
# Which walk, and over what
# --------------------------------------------------------------------------- #
async def test_neither_walk_reserves_its_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The background courtesy does not work on this surface, so it is not used.

    A reserving caller will not touch a token until it has sat free for 120 s,
    and `acquire` accumulates that wait across attempts against a 240 s cap. On
    a bucket of one token a minute it does not yield a window — it refuses its
    own request. Measured twice on NEVA 2026-09-23/24: the window never reached
    its second page, and the last thirteen reports never went out at all,
    «would need 360s of queueing (cap 240s)» on every sweep.

    What the reserve was for is still there, one level up: the lane stands
    aside outright while the forward harvest holds its lock.
    """
    seen: dict[str, float] = {}

    async def _window(*, reports: Any, reserve_seconds: float = 0.0, **_k: Any) -> WindowWalk:
        seen["window"] = reserve_seconds
        return WindowWalk(rows=1, ok=True, next_cursor=None)

    async def _by_id(*, reports: Any, reserve_seconds: float = 0.0, **_k: Any) -> SettlementWalk:
        seen["by_id"] = reserve_seconds
        return SettlementWalk(rows=1, windows_failed=0, completed_through=None)

    monkeypatch.setattr(batch, "walk_settlement_window", _window)
    monkeypatch.setattr(batch, "walk_settlement_reports", _by_id)

    _backlog(
        monkeypatch,
        due=(_report(900, weeks_back=7), _report(901, weeks_back=8)),
        outstanding=2,
        total=10,
    )
    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    _backlog(monkeypatch, due=(_report(902, weeks_back=9),), outstanding=1, total=10)
    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert seen == {"window": 0.0, "by_id": 0.0}


async def test_a_scattered_backlog_is_not_spanned_by_one_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A window fetches every row in its span, held reports included.

    Taking the twelve newest owed reports and spanning them sounds equivalent
    to fetching them and is not: once the backlog is scattered, twelve reports
    can span most of a seller's history, and the extra is not bandwidth but
    PAGES — the thing WB rates.

    NEVA found it on 2026-09-24. Fifteen reports left, scattered, the span
    reached across the archive, and the tick died to `SoftTimeLimitExceeded` —
    which the lane does not catch, so it recorded nothing and re-enqueued
    nothing, sixteen hours into a fill that should have taken minutes.
    """
    newest = _report(900, weeks_back=7)
    held_in_between = _report(901, weeks_back=8)
    older = _report(902, weeks_back=9)
    _backlog(
        monkeypatch,
        due=(newest, older),
        outstanding=2,
        total=10,
        listed=(newest.header, held_in_between.header, older.header),
    )
    by_id = _fetch(monkeypatch)
    windows = _fetch_window(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert windows == [], "a report we hold sat between them; that is two runs, not one"
    assert _ids(by_id) == [900, 902], "both owed reports, one request each — what scatter costs"


async def test_a_run_stops_at_the_first_report_we_already_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run is what the window may span — the rest waits for the next tick.

    Two owed, then a held one, then two more owed. The first two are a run and
    go in one request; the pair behind the held report is a different run and is
    not reached into.
    """
    due = (
        _report(900, weeks_back=7),
        _report(901, weeks_back=8),
        _report(903, weeks_back=10),
        _report(904, weeks_back=11),
    )
    held = _report(902, weeks_back=9)
    _backlog(
        monkeypatch,
        due=due,
        outstanding=4,
        total=10,
        listed=(due[0].header, due[1].header, held.header, due[2].header, due[3].header),
    )
    _fetch(monkeypatch)
    windows = _fetch_window(monkeypatch)

    await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert [report.report_id for report in windows[0]] == [900, 901]


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


async def test_a_window_too_wide_for_one_tick_is_paused_and_resumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix for a lane that re-fetched the same 300 000 rows every sweep.

    A contiguous run can still be wider than a tick can pay for — NEVA's spring
    2025 reports are ~65 000 rows each, five times its own mean. Before this the
    tick hit its deadline, reported a failed window, and the next sweep started
    the same span from zero: rows committed, nothing booked, for ever.

    The walk now hands back its `rrdId`, the cursor carries the span, and the
    ceiling stays put — a window still open has not been attempted, and moving
    past it would be the same abandonment by another route.
    """
    due = (_report(900, weeks_back=7), _report(901, weeks_back=8))
    _backlog(monkeypatch, due=due, outstanding=2, total=10)
    _fetch(monkeypatch)

    async def _paused(*, reports: Any, **_k: Any) -> WindowWalk:
        return WindowWalk(rows=300_000, ok=True, next_cursor=987654321)

    monkeypatch.setattr(batch, "walk_settlement_window", _paused)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.rows == 300_000
    assert step.cursor is not None
    resumed = discovery.parse_cursor(step.cursor)
    assert resumed is not None
    ceiling, _sweep, _at_start, in_flight = resumed
    assert ceiling == TODAY, "the ceiling must not pass a window that is still open"
    assert in_flight is not None
    assert in_flight.cursor == 987654321
    assert (in_flight.span_from, in_flight.span_to) == (
        due[-1].header.date_from,  # type: ignore[union-attr]
        due[0].date_to,
    )


async def test_a_resumed_window_continues_the_same_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And it picks up where it stopped, rather than re-choosing a run.

    The rows a paused window already wrote may make some of its reports stop
    looking owed, so re-deriving the run from the backlog would leave the
    window booking a subset of what it fetched. The span is a fact about the
    moment it started, so it is carried, not recomputed.
    """
    due = (_report(900, weeks_back=7), _report(901, weeks_back=8))
    _backlog(monkeypatch, due=due, outstanding=2, total=10)
    _fetch(monkeypatch)
    asked: list[Any] = []

    async def _resume(*, reports: Any, cursor: int = 0, **_k: Any) -> WindowWalk:
        asked.append((tuple(r.report_id for r in reports), cursor))
        return WindowWalk(rows=5, ok=True, next_cursor=None)

    monkeypatch.setattr(batch, "walk_settlement_window", _resume)
    open_window = discovery.InFlight(
        due[-1].header.date_from,  # type: ignore[union-attr]
        due[0].date_to,
        987654321,
    )

    step = await walk.advance_pnl(
        _tokens(),
        cursor=discovery.format_cursor(TODAY, 1, 2, open_window),
        build_ingestion=object(),
    )

    assert asked == [((900, 901), 987654321)]
    assert step.cursor is not None
    assert (discovery.parse_cursor(step.cursor) or (None, 0, 0, None))[3] is None, (
        "a finished window must leave the cursor"
    )
