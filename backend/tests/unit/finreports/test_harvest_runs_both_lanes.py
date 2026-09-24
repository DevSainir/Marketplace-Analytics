"""One tick covers both settlement lanes, in one order, under one lock.

The weekly realization report and WB's per-day reports are the same rows cut at
different boundaries, and both are fetched from the same Finance methods — one
request per minute each. As two separate schedules they took the same harvest
lock, so an overlap meant the loser returned ``skipped_locked`` and fetched
nothing; on «Обновить» that landed at the one moment somebody had asked.

So the tail runs inside the settled harvest's own tick. Two properties of that
arrangement are worth pinning, because both are invisible in any counter:

* **settled first.** The weekly walk moves the frontier and the tail covers only
  what lies past it. Run the other way round, the one tick a week a weekly report
  lands would spend a request per day on days that report was about to settle,
  and leave those rows carrying a provisional ``report_id`` until something
  overwrote them.
* **the tail is not behind the weekly gate.** «WB has nothing newer weekly» is
  precisely when yesterday is only reachable through the daily lane, and the
  settled half answers that with a ``continue``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.harvest import fleet
from src.modules.finreports.tasks.harvest.fleet import harvest_all_workspaces
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.workspaces.contract import WorkspaceTokenBundle
from tests.support.fakes import FakeRedis

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
TODAY = date(2026, 9, 23)
SETTLED = date(2026, 9, 20)
CHECKED_AT = datetime(2026, 9, 23, 9, 0, tzinfo=UTC)


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    """The walk's own mark, level with the weekly coverage."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SETTLED

    async def advance_to(self, *, workspace_id: uuid.UUID, day: date) -> date:
        return day


class _FakeReportRepo:
    """Coverage and held ids, enough for the loop to reach both lanes."""

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        return SETTLED

    async def report_ids_since(self, *, workspace_id: uuid.UUID, since: date) -> set[int]:
        return set()

    async def incomplete_report_ids(self, *, workspace_id: uuid.UUID) -> set[int]:
        """Nothing here is short of its own rows.

        Production subtracts these from «held», because a header written beside
        the first batch outlives a fetch that died half-way. This fixture's
        headers are whole, so the honest answer is an empty set.
        """
        return set()

    async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
        return []


@pytest.fixture
def order(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wire a fleet of one and record which lane ran, in order.

    Both lanes are replaced: what is under test is the loop that calls them, and
    either left real would open a session and reach WB.
    """
    ran: list[str] = []
    redis = FakeRedis()
    bundle = WorkspaceTokenBundle(
        workspace_id=WORKSPACE, name="Демо", statistics="stat", finance="a-finance-token"
    )

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return [bundle]

    async def _never_blocked(*_args: object, **_kwargs: object) -> float:
        return 0.0

    async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {}

    async def _verdict(**_kwargs: object) -> FreshnessVerdict:
        """Re-reading the coverage after a walk opens a session of its OWN.

        In `tasks.freshness`, not here — so patching this module's
        `AsyncSessionLocal` does not cover it, and left real it reaches Postgres:
        green on a laptop with Docker up, `Temporary failure in name resolution`
        in CI. It is the settled lane's business, and this file is about the
        order the two lanes run in.
        """
        return FreshnessVerdict(outcome=FreshnessOutcome.WB_HAS_NEW, checked_at=CHECKED_AT)

    async def _weekly(**_kwargs: object) -> dict[str, int]:
        ran.append("weekly")
        return {"finance": 1, "finance_windows_failed": 0}

    async def _tail(**_kwargs: object) -> dict[str, int]:
        ran.append("tail")
        return {"reports": 1, "rows": 5, "reports_failed": 0}

    monkeypatch.setattr(fleet, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(fleet, "settlement_blocked_for", _never_blocked)
    monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
    monkeypatch.setattr(fleet, "gap_repair_due", _no_repairs)
    monkeypatch.setattr(fleet, "moscow_today", lambda: TODAY)
    monkeypatch.setattr(fleet, "verdict_from_walk", _verdict)
    monkeypatch.setattr(fleet, "harvest_workspace", _weekly)
    monkeypatch.setattr(fleet, "tail_one_workspace", _tail)
    return ran


async def _no_repairs(*_args: object, **_kwargs: object) -> set[uuid.UUID]:
    """No workspace is due a gap repair — that is a separate file's subject."""
    return set()


def _gate(
    monkeypatch: pytest.MonkeyPatch, *, outcome: FreshnessOutcome, reports: tuple[Any, ...]
) -> None:
    """Make the freshness gate answer one way for every workspace."""

    async def _check(**_kwargs: object) -> tuple[FreshnessVerdict, tuple[Any, ...], tuple[()]]:
        return (
            FreshnessVerdict(
                outcome=outcome, checked_at=CHECKED_AT, probe_from=SETTLED, probe_to=SETTLED
            ),
            reports,
            (),
        )

    monkeypatch.setattr(fleet, "check_freshness", _check)


async def test_a_new_weekly_report_is_walked_before_the_tail_runs(
    order: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settled first: the walk moves the frontier the tail measures itself from."""
    _gate(
        monkeypatch,
        outcome=FreshnessOutcome.WB_HAS_NEW,
        reports=(MissingReport(report_id=989438999, date_to=SETTLED),),
    )

    totals = await harvest_all_workspaces(days=28)

    assert order == ["weekly", "tail"]
    assert totals["daily_tail_rows"] == 5


async def test_a_tick_with_nothing_newer_weekly_still_runs_the_tail(
    order: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The six days a week the weekly gate finds nothing are the tail's days."""
    _gate(monkeypatch, outcome=FreshnessOutcome.WB_EMPTY, reports=())

    totals = await harvest_all_workspaces(days=28)

    assert order == ["tail"], "the settled walk had nothing to do, the tail did"
    assert totals["daily_tail_reports"] == 1


async def test_a_standing_block_stops_both_lanes(
    order: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one verdict the tail must respect.

    Walking into an open refusal does not fetch the day — it lengthens the
    refusal. Every other «skip» is a claim about the data, which the tail is
    entitled to disagree with; this one is a claim about the channel.
    """
    _gate(monkeypatch, outcome=FreshnessOutcome.RATE_BLOCKED, reports=())

    totals = await harvest_all_workspaces(days=28)

    assert order == []
    assert totals["daily_tail_reports"] == 0


async def test_sellers_are_harvested_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """The waiting is what parallelises, and there is a minute of it per seller.

    A tick asks WB twice per workspace — the weekly list and the daily one — and
    `sales-reports/list` is one token per minute, so the second call waits. WB
    meters per seller ACCOUNT, so one seller's wait says nothing about another's:
    run sequentially, a fleet tick is a minute per seller of mostly sitting
    still, with the harvest lock held throughout and «Обновить» answering «уже
    выполняется» for a third of every quarter-hourly window.

    Asserted by overlap rather than by wall clock: each seller reports when it
    started and finished, and a sequential loop cannot produce an overlap.
    """
    live = 0
    peak = 0
    bundles = [
        WorkspaceTokenBundle(
            workspace_id=uuid.uuid5(uuid.NAMESPACE_DNS, name), name=name, finance="a-token"
        )
        for name in ("Демо", "NEVA", "Олег")
    ]

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return bundles

    async def _tail(**_kwargs: object) -> dict[str, int]:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        # Yields control the way a paced WB call does, which is the only way a
        # sequential loop and a concurrent one differ here.
        await asyncio.sleep(0)
        live -= 1
        return {"reports": 0, "rows": 0, "reports_failed": 0}

    async def _never_blocked(*_args: object, **_kwargs: object) -> float:
        return 0.0

    async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {}

    redis = FakeRedis()
    monkeypatch.setattr(fleet, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(fleet, "settlement_blocked_for", _never_blocked)
    monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
    monkeypatch.setattr(fleet, "gap_repair_due", _no_repairs)
    monkeypatch.setattr(fleet, "moscow_today", lambda: TODAY)
    monkeypatch.setattr(fleet, "tail_one_workspace", _tail)
    _gate(monkeypatch, outcome=FreshnessOutcome.WB_EMPTY, reports=())

    await harvest_all_workspaces(days=28)

    assert peak > 1, "sellers were harvested one after another"
    assert peak <= fleet._FLEET_CONCURRENCY, "and never more at once than the bound allows"


async def test_one_sellers_failure_does_not_take_the_fleet_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seller whose harvest raises is counted as failed; the others finish.

    Since the fleet went concurrent a bare ``gather`` let the first exception out
    while the other sellers were mid-walk: the task tore down their engine under
    them, and autoretry re-ran the whole fleet for one seller's fault.
    """
    bundles = [
        WorkspaceTokenBundle(
            workspace_id=uuid.uuid5(uuid.NAMESPACE_DNS, name), name=name, finance="a-token"
        )
        for name in ("Демо", "NEVA", "Олег")
    ]

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return bundles

    async def _tail(*, tokens: WorkspaceTokenBundle, **_kwargs: object) -> dict[str, int]:
        await asyncio.sleep(0)
        if tokens.name == "NEVA":
            raise RuntimeError("connection to server was closed")
        return {"reports": 1, "rows": 10, "reports_failed": 0}

    async def _never_blocked(*_args: object, **_kwargs: object) -> float:
        return 0.0

    async def _no_gaps(*_args: object, **_kwargs: object) -> dict[uuid.UUID, list[date]]:
        return {}

    redis = FakeRedis()
    monkeypatch.setattr(fleet, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(fleet, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(fleet, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(fleet, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(fleet, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(fleet, "settlement_blocked_for", _never_blocked)
    monkeypatch.setattr(fleet, "survey_settlement_gaps", _no_gaps)
    monkeypatch.setattr(fleet, "gap_repair_due", _no_repairs)
    monkeypatch.setattr(fleet, "moscow_today", lambda: TODAY)
    monkeypatch.setattr(fleet, "tail_one_workspace", _tail)
    _gate(monkeypatch, outcome=FreshnessOutcome.WB_EMPTY, reports=())

    totals = await harvest_all_workspaces(days=28)

    assert (totals["daily_tail_reports"], totals["workspaces_failed"]) == (2, 1)
