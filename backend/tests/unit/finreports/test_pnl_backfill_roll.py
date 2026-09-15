"""What the P&L lane does when a SPAN ends — the gap between two green suites.

``test_pnl_backfill_cursor`` proves :func:`next_span` finds a hole in the middle
of a seller's history, and it passed all along. It was never asked whether
anything CALLS it. Nothing did: both of the walk's terminal branches returned
``finished=True`` directly, so the lane ended itself the moment its first span
ran out, and :func:`_roll_to_next_span` sat there with no callers at all.

NEVA paid for the distinction on 2026-09-12. Its lane walked the three years that
predate the account, got the three empty answers that correctly conclude that
span, and reported «История P&L собрана» over a 715-day hole — 1033/1033, four
green lanes, a Telegram message announcing success, and not one settlement row
fetched in thirteen hours.

So these tests drive ``advance_pnl`` itself across the boundary. A unit test of
the chooser cannot fail while the walk ignores the chooser; a test of the walk
can.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.modules.finreports.tasks.backfill import walk
from src.modules.finreports.tasks.backfill.span import PNL_EMPTY_STOP, _format_cursor, _parse_cursor
from src.modules.workspaces.schemas import WorkspaceTokenBundle

TODAY = date(2026, 9, 12)

#: NEVA's real coverage on the morning the lane lied: a 45-day block at the very
#: beginning, a 715-day hole, and the weeks the forward harvest has been filling.
VIA_COVERAGE = [
    *(date(2024, 7, 11) + timedelta(days=n) for n in range(45)),
    *(date(2026, 8, 9) + timedelta(days=n) for n in range(29)),
]

#: The hole that matters, and that the lane declared complete: 2024-08-25 to
#: 2026-08-08. The walk takes it NEWEST chunk first, so this is the span a
#: healthy lane picks up before anything else.
NEWEST_CHUNK = (date(2026, 7, 9), date(2026, 8, 8))

#: The chunk immediately below it — where a concluded span must roll to.
NEXT_CHUNK_DOWN = (date(2026, 6, 8), date(2026, 7, 8))

#: The span that predates the account. WB answers it empty, correctly, and the
#: walk only reaches it once the ceiling has passed everything newer.
PREHISTORY = (date(2021, 9, 13), date(2024, 7, 10))


def _tokens() -> WorkspaceTokenBundle:
    return WorkspaceTokenBundle(
        workspace_id=uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d"),
        name="NEVA",
        statistics="token",
    )


@pytest.fixture(autouse=True)
def _no_wb(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything outside the decision under test, held still.

    The walk's choice of span is pure given (coverage, today, cursor); the gate
    and the page fetch only decide WHICH branch it reaches. Each test says what
    WB answered by patching ``_ingest_one_page`` and nothing else.
    """

    class _Gate:
        async def acquire(self, _path: str, *, reserve_seconds: float = 0.0) -> None:
            # The reserve is asserted in test_pnl_backfill_yields; here it only
            # has to be accepted, or every roll test fails for the wrong reason.
            return None

    monkeypatch.setattr(walk, "statistics_rate_gate", lambda *_a, **_k: _Gate())
    monkeypatch.setattr(walk, "moscow_today", lambda: TODAY)

    # These cases are NEVA's real history and it spans two years, so the walk is
    # given the depth it had at the time. Production now asks for three months
    # (a business decision, priced in PNL_FLOOR_DAYS) — pinning that number here
    # would mean the next change to how much history a seller gets quietly
    # deleted the regression for the bug that lost NEVA two years of it.
    monkeypatch.setattr(walk, "PNL_FLOOR_DAYS", 5 * 365)

    async def _coverage(_workspace_id: uuid.UUID) -> list[date]:
        return VIA_COVERAGE

    monkeypatch.setattr(walk, "read_settled_days", _coverage)


def _answer(monkeypatch: pytest.MonkeyPatch, outcome: tuple[int, int | None] | None) -> None:
    """Make WB answer every page of this test the same way."""

    async def _page(**_kwargs: Any) -> tuple[int, int | None] | None:
        return outcome

    monkeypatch.setattr(walk, "_ingest_one_streamed_page", _page)


async def test_an_exhausted_span_moves_to_the_next_hole_instead_of_ending_the_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact failure, as an assertion.

    Three empty answers conclude the PRE-HISTORY span and nothing more. A lane
    that reports ``finished`` here is claiming a 715-day hole is filled.
    """
    _answer(monkeypatch, (0, None))
    cursor = _format_cursor(*NEWEST_CHUNK, 0, PNL_EMPTY_STOP - 1, NEWEST_CHUNK[1])

    step = await walk.advance_pnl(_tokens(), cursor=cursor, build_ingestion=object())

    assert not step.finished, "the lane ended itself on a span that was merely empty"
    assert step.cursor is not None
    span_from, span_to, _rrd, _empties, _search = _parse_cursor(step.cursor)
    assert (span_from, span_to) == NEXT_CHUNK_DOWN


async def test_the_last_page_of_a_span_moves_on_rather_than_finishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second terminal branch, which had the same bug and the same cause.

    A short non-empty page is ordinary pagination: WB has served this window to
    its end. That ends the WINDOW. Whether it ends the lane is a question only
    the coverage can answer.
    """
    _answer(monkeypatch, (120, None))
    cursor = _format_cursor(*NEWEST_CHUNK, 4242, 0, NEWEST_CHUNK[1])

    step = await walk.advance_pnl(_tokens(), cursor=cursor, build_ingestion=object())

    assert not step.finished
    assert step.cursor is not None
    assert _parse_cursor(step.cursor)[:2] == NEXT_CHUNK_DOWN


async def test_the_search_ceiling_moves_below_the_span_just_concluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise the walk re-offers the same stretch for ever.

    The ceiling is what makes the roll terminate: a span WB will never serve is
    concluded once, and the next search starts further back. It moves DOWN now,
    because the walk runs newest to oldest.
    """
    _answer(monkeypatch, (0, None))
    cursor = _format_cursor(*NEWEST_CHUNK, 0, PNL_EMPTY_STOP - 1, NEWEST_CHUNK[1])

    step = await walk.advance_pnl(_tokens(), cursor=cursor, build_ingestion=object())

    assert step.cursor is not None
    assert _parse_cursor(step.cursor)[4] < NEWEST_CHUNK[0]


async def test_a_lane_with_no_holes_left_really_does_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The roll must still be able to END. A lane that never finishes is a leak.

    Contiguous coverage from the seller's first report onward leaves nothing to
    ask for, and the days after the newest row belong to the forward harvest.
    """
    contiguous = [date(2026, 6, 1) + timedelta(days=n * 7) for n in range(14)]

    async def _coverage(_workspace_id: uuid.UUID) -> list[date]:
        return contiguous

    monkeypatch.setattr(walk, "read_settled_days", _coverage)
    _answer(monkeypatch, (0, None))
    cursor = _format_cursor(
        date(2021, 9, 13), date(2026, 5, 31), 0, PNL_EMPTY_STOP - 1, date(2021, 9, 13)
    )

    step = await walk.advance_pnl(_tokens(), cursor=cursor, build_ingestion=object())

    assert step.finished
    assert step.cursor is None


async def test_a_new_workspace_is_walked_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rule, stated where a new seller actually meets it.

    Signup is the case that matters: the lane has no coverage to reason from, so
    nothing but the direction decides whether the seller's first settlement rows
    are this month's or two years ago's.
    """
    _answer(monkeypatch, (0, None))

    async def _nothing(_workspace_id: uuid.UUID) -> list[date]:
        return []

    monkeypatch.setattr(walk, "read_settled_days", _nothing)
    monkeypatch.setattr(walk, "PNL_FLOOR_DAYS", 90)

    step = await walk.advance_pnl(_tokens(), cursor=None, build_ingestion=object())

    assert step.cursor is not None
    _span_from, span_to, _rrd, _empties, _search = _parse_cursor(step.cursor)
    assert (TODAY - span_to).days <= 2, "started at the oldest end of the depth"
