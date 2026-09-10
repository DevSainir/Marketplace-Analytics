"""The harvest gets a second chance at days its watermark has already passed.

The ordinary walk can only move forward. ``_walk_span`` starts AT the watermark,
and the watermark jumps to the newest report's stated end — so the moment a
weekly report lands, every earlier day leaves the reachable window and the
freshness gate, which probes the day *after* the watermark, never asks about
them again.

WB does not publish in that order. It forms single-day supplementary reports and
starts serving their detail rows later. On 2026-08-31 the two facts met: report
983241109 covered 31.08 alone and was formed on 09-01, yet on 09-06 all eighty
probes over 31.08..05.09 answered 204 — WB was not serving it. On 09-07 the
01.09-06.09 report landed, the watermark jumped to 09-06, and the day was out of
reach before WB ever served it. Every workspace lost a day of settlement, and
nothing in the product could tell: the task succeeded, the counters moved, the
P&L was simply short.

These tests pin the two halves of the answer, because either alone is useless:
the span reaches back, and the pass runs even when the gate says there is
nothing newer — which is true, and beside the point, exactly when a back-dated
report is what is being looked for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from src.modules.finreports.constants import HARVEST_LOCK_KEY, RECONCILE_LOOKBACK_DAYS
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessVerdict,
)
from src.modules.finreports.tasks import freshness, harvest
from src.modules.finreports.tasks.harvest import harvest_all_workspaces
from src.modules.finreports.tasks.spans import reconciliation_slice, walk_span
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000ab99")
TODAY = date(2026, 9, 8)
#: Where the watermark stood once the 01.09-06.09 report had landed.
SETTLED = date(2026, 9, 6)
#: The day that fell out of reach behind it.
LOST_DAY = date(2026, 8, 31)


# --- the span -------------------------------------------------------------


def test_the_hourly_span_still_starts_at_the_watermark() -> None:
    """The ordinary tick must not re-read days it already holds.

    Each week of span is a WB request on a surface that serves one per quarter
    of an hour, so a lookback on the hourly path would spend most of a day's
    budget re-reading settled data.
    """
    span = walk_span(latest_settled=SETTLED, today=TODAY, days=28)

    assert span == (SETTLED, date(2026, 9, 7))


def test_a_reconciliation_span_reaches_behind_the_watermark() -> None:
    """The whole mechanism: the start moves back, so passed days are asked about again."""
    span = walk_span(latest_settled=SETTLED, today=TODAY, days=28, lookback_days=14)

    assert span == (date(2026, 8, 23), date(2026, 9, 7))


def test_the_lookback_covers_the_day_that_was_lost() -> None:
    """Sized against the incident, not chosen for roundness.

    31.08 became fetchable only once WB began serving it, which was after the
    07.09 jump — eight days after the day it covers. The constant has to still
    reach that far back on the day it becomes reachable, or the pass would have
    missed this too.
    """
    date_from, date_to = walk_span(
        latest_settled=SETTLED, today=TODAY, days=28, lookback_days=RECONCILE_LOOKBACK_DAYS
    )

    assert date_from <= LOST_DAY <= date_to


def test_a_reconciliation_span_never_outruns_the_backfill_floor() -> None:
    """``days`` still bounds it, so the lookback cannot turn into a full re-harvest."""
    span = walk_span(latest_settled=SETTLED, today=TODAY, days=3, lookback_days=90)

    assert span == (date(2026, 9, 4), date(2026, 9, 7))


def test_a_never_harvested_workspace_is_unaffected_by_the_lookback() -> None:
    """It already walks the full backfill; there is nothing behind it to reach."""
    assert walk_span(latest_settled=None, today=TODAY, days=28, lookback_days=14) == walk_span(
        latest_settled=None, today=TODAY, days=28
    )


# --- the ration -----------------------------------------------------------


def _fleet(count: int) -> list[WorkspaceTokenBundle]:
    """``count`` workspaces with stable, distinguishable ids."""
    return [
        WorkspaceTokenBundle(
            workspace_id=uuid.UUID(f"019f657a-0000-7000-8000-{n:012d}"),
            name=f"ws-{n}",
            statistics="stat-token",
        )
        for n in range(count)
    ]


def test_a_reconciliation_run_takes_exactly_one_workspace() -> None:
    """Measured on prod: each window is a full WB refill of WAITING, not of work.

    The walk's two windows queued 633.8 s and 944.5 s while the requests
    themselves took seconds, so a three-window span is ~45 minutes — and the
    workspaces are walked in sequence, making the fleet cost a sum. Five sellers
    would hold the platform-wide harvest lock for three to four hours, growing
    with every seller added.
    """
    assert len(reconciliation_slice(_fleet(5), today=TODAY)) == 1


def test_the_ration_is_flat_in_the_size_of_the_fleet() -> None:
    """The whole point: a new seller must not lengthen the nightly pass."""
    assert len(reconciliation_slice(_fleet(50), today=TODAY)) == 1


def test_every_workspace_comes_round_within_one_cycle() -> None:
    """Round-robin, not a favourite: a workspace nobody reconciles is one that
    silently loses days again — the exact failure this pass exists to end."""
    fleet = _fleet(5)

    picked = {
        reconciliation_slice(fleet, today=date.fromordinal(TODAY.toordinal() + offset))[
            0
        ].workspace_id
        for offset in range(5)
    }

    assert picked == {bundle.workspace_id for bundle in fleet}


def test_the_rotation_survives_the_loader_reshuffling_its_rows() -> None:
    """The order is a query result, not a promise.

    Sorted before rotating, or a reshuffle could pick one workspace twice
    running while another waited a fortnight for a turn that never came.
    """
    fleet = _fleet(5)

    first = reconciliation_slice(fleet, today=TODAY)[0].workspace_id
    shuffled = reconciliation_slice(list(reversed(fleet)), today=TODAY)[0].workspace_id

    assert first == shuffled


def test_an_empty_fleet_reconciles_nothing() -> None:
    """No tenants, no walk — and no IndexError on the modulo."""
    assert reconciliation_slice([], today=TODAY) == []


def test_a_fleet_outgrowing_the_lookback_says_so(caplog: pytest.LogCaptureFixture) -> None:
    """The scaling limit is announced rather than silently losing days.

    A workspace waits `len(fleet)` days for its turn, so the lookback has to
    still cover a back-dated report when that turn arrives. Past that point the
    pass quietly stops catching what it was built for — which is precisely how
    31.08 was lost in the first place.
    """
    with caplog.at_level("WARNING"):
        reconciliation_slice(_fleet(RECONCILE_LOOKBACK_DAYS), today=TODAY)

    assert "lookback" in caplog.text


def test_a_fleet_well_inside_the_lookback_stays_quiet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A warning that fires at today's size would be furniture by next week."""
    with caplog.at_level("WARNING"):
        reconciliation_slice(_fleet(5), today=TODAY)

    assert caplog.text == ""


# --- the pass -------------------------------------------------------------


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


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeWatermarkRepo:
    """Reports the watermark as it stood once the weekly report had landed."""

    def __init__(self, _session: object) -> None:
        pass

    async def get(self, *, workspace_id: uuid.UUID) -> date:
        return SETTLED


class _FakeReportRepo:
    """Coverage after the walk — unchanged, which is the quiet-week case."""

    def __init__(self, _session: object) -> None:
        pass

    async def latest_settled_date(self, *, workspace_id: uuid.UUID) -> date | None:
        return SETTLED


@pytest.fixture
def walked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[date, date]]:
    """Wire a fleet of one whose gate says there is nothing newer.

    That verdict is the honest one all through this incident — WB really had
    published nothing past the watermark — and it is exactly what a
    back-dated report has to survive.
    """
    spans: list[tuple[date, date]] = []
    redis = _FakeRedis()

    bundle = WorkspaceTokenBundle(workspace_id=WORKSPACE, name="Демо", statistics="stat-token")

    async def _bundles(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        return [bundle]

    async def _bundle(*_args: object, **_kwargs: object) -> WorkspaceTokenBundle:
        return bundle

    async def _check(**_kwargs: object) -> FreshnessVerdict:
        return FreshnessVerdict(
            outcome=FreshnessOutcome.WB_EMPTY,
            checked_at=datetime(2026, 9, 8, 3, 0, tzinfo=UTC),
            probe_from=date(2026, 9, 7),
            probe_to=date(2026, 9, 7),
        )

    async def _walk(
        *, tokens: WorkspaceTokenBundle, date_from: date, date_to: date, **_kwargs: object
    ) -> dict[str, int]:
        spans.append((date_from, date_to))
        return {"finance_windows_failed": 0}

    monkeypatch.setattr(harvest, "get_redis", lambda: redis)
    monkeypatch.setattr(freshness, "get_redis", lambda: redis)
    monkeypatch.setattr(harvest, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(freshness, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(harvest, "SettlementWatermarkRepository", _FakeWatermarkRepo)
    monkeypatch.setattr(freshness, "FinancialReportRepository", _FakeReportRepo)
    monkeypatch.setattr(harvest, "load_workspace_token_bundles", _bundles)
    monkeypatch.setattr(harvest, "load_workspace_token_bundle", _bundle)
    monkeypatch.setattr(harvest, "check_freshness", _check)
    monkeypatch.setattr(harvest, "harvest_workspace", _walk)
    monkeypatch.setattr(harvest, "moscow_today", lambda: TODAY)
    return spans


async def test_an_ordinary_tick_still_skips_when_nothing_is_newer(
    walked: list[tuple[date, date]],
) -> None:
    """The gate keeps its job — this pass must not turn every hour into a walk."""
    totals = await harvest_all_workspaces(days=28)

    assert walked == []
    assert totals["workspaces_skipped"] == 1


async def test_the_reconciliation_pass_walks_despite_a_gate_that_says_no(
    walked: list[tuple[date, date]],
) -> None:
    """«Ничего новее нет» is true and irrelevant when the missing report is older.

    The gate probes the day AFTER the watermark, so it cannot see a back-dated
    report even in principle. Letting its verdict stop the pass would leave the
    lookback span unreachable and the fix inert.
    """
    await harvest_all_workspaces(days=28, reconcile=True)

    assert len(walked) == 1


async def test_the_reconciliation_pass_asks_about_the_day_that_was_lost(
    walked: list[tuple[date, date]],
) -> None:
    """The two halves together: it runs, and it runs over the right span."""
    await harvest_all_workspaces(days=28, reconcile=True)

    date_from, date_to = walked[0]
    assert date_from <= LOST_DAY <= date_to


async def test_the_reconciliation_pass_still_respects_the_harvest_lock(
    walked: list[tuple[date, date]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is the same walk against the same WB budget, so it queues like one.

    Two of these racing would spend a seller's quarter-hourly settlement budget
    twice over — the failure the lock exists to prevent, and one the extra span
    would make more expensive, not less.
    """
    held = _FakeRedis()
    held.store[HARVEST_LOCK_KEY] = "another-runs-token"
    monkeypatch.setattr(harvest, "get_redis", lambda: held)

    totals = await harvest_all_workspaces(days=28, reconcile=True)

    assert walked == []
    assert totals["skipped_locked"] == 1


async def test_the_button_never_triggers_a_reconciliation(
    walked: list[tuple[date, date]],
) -> None:
    """«Обновить» is a forward question, and the expensive span is not its to spend.

    A seller pressing refresh wants the report WB has just published. Widening
    their click into a fortnight of re-reads would spend their whole settlement
    budget on data already on file — and the daily pass covers it anyway.
    """
    await harvest_all_workspaces(days=28, workspace_id=WORKSPACE)

    assert walked == []
