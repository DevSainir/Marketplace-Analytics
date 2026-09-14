"""A day the walk asked about and found empty is not a settled day.

The third time this door has been closed, and the reason it kept re-opening is
that both dates describing "where the history ends" over-claim — in opposite
directions, so fixing either one alone moves the failure rather than ending it.

* `max(financial_report.date_to)` is what WB *states*, written from the first
  page that lands. A week walked one day deep already claims all six; trusting
  it skipped five of six days on 2026-09-07.
* The walk's watermark is what was *asked*, and a window WB answers **empty**
  completes exactly like one that returned rows. WB forms a week's report the
  day after the week ends, so every Sunday-night tick asks about the open week,
  is told nothing, and certifies the whole of it.

On 2026-09-14 the second one cost the week: watermark 13.09, newest report
ending 06.09, and report 985672101 (07.09-13.09, formed 14.09) published into a
window nothing would ever ask about again. Three of five workspaces were short
the entire week while the hourly gate answered «settled through 13.09 — nothing
newer can exist yet» to every tick, «Обновить» included. No counter moved and no
alert fired, because a run that skips looks exactly like a week WB was quiet.

So the frontier is the EARLIER of the two, and each date is a ceiling on the
other. These tests pin that, and the one below them pins the place it is read —
the harvest loop — because a rule nothing consults is the shape the last two
fixes had.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.finreports.tasks import freshness, harvest
from src.modules.finreports.tasks.freshness import probe_window
from src.modules.finreports.tasks.harvest import harvest_all_workspaces
from src.modules.finreports.tasks.spans import settlement_frontier, walk_span
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-000000841605")
TODAY = date(2026, 9, 14)
#: Where the walk had marched to, over days WB had published nothing for.
WATERMARK = date(2026, 9, 13)
#: The last day a report we actually hold covers.
COVERED = date(2026, 9, 6)
#: The week WB published on the morning of 09-14, report 985672101.
MISSED_WEEK = (date(2026, 9, 7), date(2026, 9, 13))
CHECKED_AT = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


# --- the rule -------------------------------------------------------------


def test_an_empty_week_the_walk_asked_about_does_not_close_the_history() -> None:
    """The 09-14 failure, at its source.

    The walk completed 07.09-13.09 and WB answered nothing, because the report
    did not exist yet. Completing a window is evidence about the asking, never
    about what WB has since published into it.
    """
    assert settlement_frontier(watermark=WATERMARK, covered_through=COVERED) == COVERED


def test_a_partly_walked_week_is_still_capped_by_the_walk() -> None:
    """The 09-07 failure must not come back as the price of fixing 09-14.

    One day of the 01.09-06.09 week fetched, the header claiming all six. The
    watermark is the lower of the two here, and it stays the answer.
    """
    frontier = settlement_frontier(watermark=date(2026, 9, 1), covered_through=date(2026, 9, 6))

    assert frontier == date(2026, 9, 1)


def test_a_workspace_holding_no_report_keeps_its_watermark() -> None:
    """There is no coverage to be behind, and the alternative is worse.

    A frontier of ``None`` reads as "never harvested", which walks the full
    backfill span — every hour, for a seller WB has simply published nothing
    for. A first report arriving late is the reconciliation pass's job, as it is
    for every other back-dated report.
    """
    assert settlement_frontier(watermark=WATERMARK, covered_through=None) == WATERMARK


def test_a_workspace_that_has_never_completed_a_window_falls_back_to_coverage() -> None:
    """Reports on file and no watermark: the rows are held, so the days are closed."""
    assert settlement_frontier(watermark=None, covered_through=COVERED) == COVERED


def test_a_fresh_workspace_has_no_frontier_at_all() -> None:
    """Neither date exists, and ``None`` is what the gate must read as "walk"."""
    assert settlement_frontier(watermark=None, covered_through=None) is None


# --- what the rule buys ---------------------------------------------------


def test_the_gate_stays_open_on_the_monday_the_report_lands() -> None:
    """The behaviour the whole change exists for.

    Read off the watermark, the window is empty and the tick skips — for good,
    since tomorrow's window starts after 13.09 and the report's rows are all
    behind it. Read off the frontier, the probe covers exactly the week WB has
    just published.
    """
    assert probe_window(latest_settled=WATERMARK, today=TODAY) is None

    frontier = settlement_frontier(watermark=WATERMARK, covered_through=COVERED)
    assert probe_window(latest_settled=frontier, today=TODAY) == MISSED_WEEK


def test_the_walk_that_follows_covers_the_week_the_probe_found() -> None:
    """A gate that opens onto a span starting after the missed week fixes nothing."""
    frontier = settlement_frontier(watermark=WATERMARK, covered_through=COVERED)

    date_from, date_to = walk_span(latest_settled=frontier, today=TODAY, days=28)

    assert date_from <= MISSED_WEEK[0]
    assert date_to >= MISSED_WEEK[1]


# --- where the rule is read -----------------------------------------------


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    """A walk that marched over the open week."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return WATERMARK


class _FakeReportRepo:
    """Coverage stopping at the last report WB actually published to us."""

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date:
        return COVERED


class _FakeRedis:
    """The lock commands plus the two the freshness record uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        key, token = args[0], args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


async def test_the_harvest_asks_the_gate_about_the_frontier_not_the_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loop is the seam the last two fixes were written and then not read at.

    Asserting on the date handed to the gate rather than on a log line: this is
    the one value that decides whether 07.09-13.09 is ever asked about again.
    """
    asked: list[date | None] = []

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return [
            WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", statistics="stat-token")
        ]

    async def _check(*, latest_settled: date | None, **_kwargs: object) -> FreshnessVerdict:
        asked.append(latest_settled)
        return FreshnessVerdict(outcome=FreshnessOutcome.WB_EMPTY, checked_at=CHECKED_AT)

    redis = _FakeRedis()
    monkeypatch.setattr(harvest, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(harvest, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(harvest, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(harvest, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(harvest, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(harvest, "moscow_today", lambda: TODAY)
    monkeypatch.setattr(harvest, "check_freshness", _check)

    await harvest_all_workspaces(days=28)

    assert asked == [COVERED]
