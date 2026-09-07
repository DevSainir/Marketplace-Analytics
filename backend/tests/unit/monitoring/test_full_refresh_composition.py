"""«Обновить» must mean the same thing as the nightly pass, and survive WB.

Two behaviours are pinned here, and both are decisions rather than plumbing.

The first is that a refresh now includes the buyout-cohort pass at all. It used
to run only on its own 07:00 MSK schedule, reachable from no button, so a seller
pressing «Обновить» and watching «Процент выкупа» not move was seeing the system
work as designed.

The second is that the cohort pass is a SOURCE, not a precondition. It is the
slowest thing in a refresh (22 sequential rate-limited requests) and the least
urgent (a cohort keeps maturing for ~3 weeks), so letting it fail the task would
throw away a completed funnel, stock and advertising harvest to report a
withheld surface the seller could have waited a day for.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from src.modules.monitoring.tasks import full_refresh
from src.modules.monitoring.tasks.full_refresh import (
    COHORT_SOURCE_LABEL,
    refresh_workspace_data,
)
from src.modules.monitoring.tasks.harvest import HarvestOutcome
from src.modules.workspaces.contract import WorkspaceTokenBundle

WORKSPACE = WorkspaceTokenBundle(
    workspace_id=uuid.uuid4(),
    name="Демо",
    content="content-token",
    analytics="analytics-token",
)

WINDOW = {"date_from": date(2026, 9, 1), "date_to": date(2026, 9, 7)}


@pytest.fixture
def harvest(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand in for the SKU-window harvest, capturing how it was called."""
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> HarvestOutcome:
        captured.update(kwargs)
        return HarvestOutcome(counts={"funnel_rows": 287, "sales_rows": 12})

    monkeypatch.setattr(full_refresh, "_harvest_sku_window", _fake)
    return captured


@pytest.fixture
def claim_granted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the cohort pass run — the ordinary case for a first refresh."""

    async def _claim(_workspace_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(full_refresh, "claim_cohort_pass", _claim)


async def test_a_refresh_pulls_the_sale_feed_and_the_cohorts(
    monkeypatch: pytest.MonkeyPatch, harvest: dict[str, Any], claim_granted: None
) -> None:
    """The whole point: one refresh, every family of WB data.

    ``include_sales`` is asserted explicitly because it is the flag that used to
    be ``False`` on this path, and flipping it back would silently restore the
    old behaviour — a green refresh with «Выкупы, ₽» standing still.
    """

    async def _cohorts(_tokens: WorkspaceTokenBundle, _days: int) -> int:
        return 44

    monkeypatch.setattr(full_refresh, "_refresh_workspace_cohorts", _cohorts)

    outcome = await refresh_workspace_data(tokens=WORKSPACE, nm_ids=[1, 2], **WINDOW)

    assert harvest["include_sales"] is True
    assert outcome.counts["funnel_rows"] == 287
    assert outcome.counts["sales_rows"] == 12
    assert outcome.counts["cohort_rows"] == 44
    assert outcome.failed_sources == ()


async def test_a_failed_cohort_pass_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, harvest: dict[str, Any], claim_granted: None
) -> None:
    """WB withholding the cohorts must not discard the rest of the harvest.

    The funnel, stock and advertising rows are already persisted by the time the
    cohort pass runs. Re-raising here would fail the task, and the SPA would
    tell the seller the refresh did not complete — about data that is sitting in
    the database.
    """

    async def _explode(_tokens: WorkspaceTokenBundle, _days: int) -> int:
        raise RuntimeError("WB served none of the 22 cohort days")

    monkeypatch.setattr(full_refresh, "_refresh_workspace_cohorts", _explode)

    outcome = await refresh_workspace_data(tokens=WORKSPACE, nm_ids=[1], **WINDOW)

    assert outcome.counts["funnel_rows"] == 287
    assert outcome.counts["cohort_rows"] == 0
    assert outcome.failed_sources == (COHORT_SOURCE_LABEL,)


async def test_a_recently_covered_workspace_skips_the_cohort_pass(
    monkeypatch: pytest.MonkeyPatch, harvest: dict[str, Any]
) -> None:
    """Refreshing six SKUs in a row costs one cohort pass, not six.

    The pass is catalogue-wide by construction — WB ignores the ``nmIDs``
    filter — so a second run within the claim window re-reads the same 22 days
    to write the same rows, for another 22 rate-limited requests.

    A skip is NOT a failure and must not be reported as a withheld source: the
    cohorts are current, which is the outcome the seller wanted.
    """

    async def _denied(_workspace_id: uuid.UUID) -> bool:
        return False

    async def _must_not_run(_tokens: WorkspaceTokenBundle, _days: int) -> int:
        raise AssertionError("the cohort pass must not run when the claim is denied")

    monkeypatch.setattr(full_refresh, "claim_cohort_pass", _denied)
    monkeypatch.setattr(full_refresh, "_refresh_workspace_cohorts", _must_not_run)

    outcome = await refresh_workspace_data(tokens=WORKSPACE, nm_ids=[1], **WINDOW)

    assert outcome.counts["funnel_rows"] == 287
    assert outcome.counts["cohort_rows"] == 0
    assert outcome.failed_sources == ()


async def test_the_nightly_fleet_walk_leaves_cohorts_to_their_own_pass(
    monkeypatch: pytest.MonkeyPatch, harvest: dict[str, Any]
) -> None:
    """The 06:00 fleet harvest must not redo what 07:00 is about to do.

    ``monitoring.refresh_buyout_cohorts`` sweeps every workspace an hour after
    ``monitoring.harvest_all``. Running the pass in both would spend 22
    rate-limited requests per workspace writing rows the 07:00 pass immediately
    rewrites — and would lengthen the nightly harvest by ~7 minutes per tenant
    for nothing.

    The claim is NOT consulted on this path, so a fleet walk can never leave a
    claim behind that suppresses the dedicated pass an hour later.
    """

    async def _must_not_claim(_workspace_id: uuid.UUID) -> bool:
        raise AssertionError("the fleet walk must not claim the cohort pass")

    async def _must_not_run(_tokens: WorkspaceTokenBundle, _days: int) -> int:
        raise AssertionError("the fleet walk must not run the cohort pass")

    monkeypatch.setattr(full_refresh, "claim_cohort_pass", _must_not_claim)
    monkeypatch.setattr(full_refresh, "_refresh_workspace_cohorts", _must_not_run)

    outcome = await refresh_workspace_data(
        tokens=WORKSPACE, nm_ids=[1], include_cohorts=False, **WINDOW
    )

    assert outcome.counts["funnel_rows"] == 287
    assert outcome.counts["cohort_rows"] == 0
    assert outcome.failed_sources == ()
