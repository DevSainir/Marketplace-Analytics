"""What the advertising lane remembers between ticks, and what it re-asks WB for.

The lane walks ~36 windows of history, up to eight campaign batches each, and
every one of those ticks used to open with the same request: «list my
campaigns». The list cannot change in a way that matters — a campaign created
mid-walk has no history behind it to collect — so every one of those calls after
the first was spent rediscovering an answer the lane already had.

That was free until it wasn't. On 2026-09-11 three concurrent ticks of one
workspace's lane each queued for that call against a bucket sized for
``/adv/v3/fullstats`` (one token per 20 s), the third crossed the 120 s queue
cap, and the lane raised — twice inside thirty minutes, which is a page.

So the campaign list rides in the cursor. These tests pin the format, the two
older formats that must keep resuming, and the thing the whole change is for:
a tick with a cursor does not call WB to ask what it already knows.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from src.modules.monitoring.services import backfill as lane
from src.modules.workspaces.contract import WorkspaceTokenBundle

TODAY = date(2026, 9, 11)
WINDOW_END = date(2026, 8, 20)


# --------------------------------------------------------------------------- #
# The cursor format
# --------------------------------------------------------------------------- #
def test_the_campaign_list_survives_a_round_trip() -> None:
    """Window, batch and campaign ids all come back out."""
    written = lane._format_adv_cursor(WINDOW_END, 3, {97455941, 90838808})

    assert lane._parse_adv_cursor(written, default_end=TODAY) == (
        WINDOW_END,
        3,
        {90838808, 97455941},
    )


def test_a_cursor_from_before_this_change_still_resumes() -> None:
    """A lane mid-walk when this shipped must not restart from yesterday.

    Both older forms exist in the wild: the date-only one the lane wrote before
    it batched, and the ``date|batch`` one it wrote until now. Each parses to
    "no ids yet", which is the caller's signal to ask WB once more.

    This is the second time the format has grown under a running lane — it
    gained the batch index the same way — and both times the failure a strict
    parser would have caused is the same one: every in-flight advertising lane
    turning into a failing tick at the exact moment of deploy.
    """
    assert lane._parse_adv_cursor("2026-08-20|3", default_end=TODAY) == (WINDOW_END, 3, None)
    assert lane._parse_adv_cursor("2026-08-20", default_end=TODAY) == (WINDOW_END, 0, None)


def test_no_cursor_starts_at_the_default_end_with_nothing_known() -> None:
    """A lane that has never ticked has neither a window nor a campaign list."""
    assert lane._parse_adv_cursor(None, default_end=TODAY) == (TODAY, 0, None)


# --------------------------------------------------------------------------- #
# What a tick actually asks WB for
# --------------------------------------------------------------------------- #
class _FakeAdvertisingClient:
    """A WB advertising client that records calls and returns nothing.

    ``list_campaigns`` raising rather than returning is deliberate: a test that
    merely counted calls would still pass if the call moved somewhere the count
    was not read.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Accept the real client's constructor signature and ignore it."""
        self.full_stats_calls: list[tuple[date, date, list[int]]] = []

    async def __aenter__(self) -> _FakeAdvertisingClient:
        """Enter the async context the lane opens."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave it."""
        return

    async def list_campaigns(self) -> list[object]:
        """Fail the test — a tick holding a campaign list must not ask again."""
        raise AssertionError("list_campaigns() was called on a tick that already had the list")

    async def fetch_full_stats(
        self, *, campaign_ids: list[int], date_from: date, date_to: date
    ) -> list[object]:
        """Record the window asked for, and answer with no rows."""
        self.full_stats_calls.append((date_from, date_to, campaign_ids))
        return []


class _EmptyResult:
    """A SQLAlchemy result that holds no rows."""

    def all(self) -> list[tuple[int, date]]:
        """No campaign has any stored coverage."""
        return []


class _FakeSession:
    """An ``AsyncSessionLocal()`` stand-in that answers every query empty."""

    async def __aenter__(self) -> _FakeSession:
        """Enter the session context."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave it."""
        return

    async def execute(self, *args: Any, **kwargs: Any) -> _EmptyResult:
        """Answer the coverage query with nothing stored."""
        return _EmptyResult()


@pytest.fixture
def wb(monkeypatch: pytest.MonkeyPatch) -> _FakeAdvertisingClient:
    """Replace the lane's WB client and DB session with recording fakes."""
    client = _FakeAdvertisingClient()
    monkeypatch.setattr(lane, "WBAdvertisingClient", lambda *a, **k: client)
    monkeypatch.setattr(lane, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(lane, "moscow_today", lambda: TODAY)
    return client


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with an advertising token and nothing else."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(), name="Тест", advertising="an-advertising-token"
    )


async def test_a_tick_with_a_campaign_list_does_not_ask_wb_for_it_again(
    wb: _FakeAdvertisingClient,
) -> None:
    """The saved call, and the reason the lane stopped paging.

    ``list_campaigns`` asserts if it is reached, so this passing IS the claim.
    """
    cursor = lane._format_adv_cursor(WINDOW_END, 0, {97455941, 90838808})

    step = await lane.advance_advertising(_tokens(), cursor=cursor)

    assert wb.full_stats_calls == [(date(2026, 7, 21), WINDOW_END, [90838808, 97455941])]
    assert not step.finished


async def test_the_next_cursor_carries_the_list_onward(wb: _FakeAdvertisingClient) -> None:
    """Whatever a tick knew, the tick after it knows too.

    Without this the list is rediscovered once and then lost again, which is the
    old behaviour wearing a new cursor.
    """
    cursor = lane._format_adv_cursor(WINDOW_END, 0, {97455941, 90838808})

    step = await lane.advance_advertising(_tokens(), cursor=cursor)

    assert step.cursor is not None
    _, _, carried = lane._parse_adv_cursor(step.cursor, default_end=TODAY)
    assert carried == {90838808, 97455941}
