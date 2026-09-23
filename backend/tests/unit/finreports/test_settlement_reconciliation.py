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

These tests pin what the pass is AIMED at — the span that reaches back behind
the watermark, and the rotation that decides whose turn it is. Both are pure
functions and need no harness. The tick that acts on them is
``test_reconciliation_pass``, and it is worth the two files: either half alone
is useless, and they fail for completely different reasons.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.constants import (
    RECONCILE_LOOKBACK_DAYS,
)
from src.modules.finreports.tasks.spans import reconciliation_slice, walk_span
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit


async def _never_blocked(_tokens: object) -> float:
    """No penalty block stands.

    Stubbed rather than left to the real gate because the real gate reaches
    Redis, and a unit test that quietly talks to a live Redis drains the
    bucket a developer's next run depends on.
    """
    return 0.0


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


def test_a_known_gap_jumps_the_rotation() -> None:
    """A detected hole must not wait its turn.

    Round-robin alone means a gap found tonight could sit unrepaired for
    `len(fleet)` nights while the detector reports it — a fault the repair is in
    no hurry to reach. It is also what lets the alert use a 26h `for:` instead of
    one long enough to cover the whole rotation.
    """
    fleet = _fleet(5)
    holed = fleet[3]

    picked = reconciliation_slice(
        fleet, today=TODAY, gaps={holed.workspace_id: [date(2026, 8, 31)]}
    )

    assert picked == [holed]


def test_the_oldest_gap_is_repaired_first() -> None:
    """Closest to ageing out of WB's reach, so it is the one that cannot wait."""
    fleet = _fleet(3)
    gaps = {
        fleet[0].workspace_id: [date(2026, 9, 5)],
        fleet[2].workspace_id: [date(2026, 8, 28)],
    }

    assert reconciliation_slice(fleet, today=TODAY, gaps=gaps) == [fleet[2]]


def test_an_empty_gap_list_is_not_a_gap() -> None:
    """The survey returns a mapping; a surveyed-and-sound workspace must not
    read as urgent just for appearing in it."""
    fleet = _fleet(5)
    plain = reconciliation_slice(fleet, today=TODAY)

    surveyed = reconciliation_slice(
        fleet, today=TODAY, gaps={bundle.workspace_id: [] for bundle in fleet}
    )

    assert surveyed == plain


def test_without_gaps_the_rotation_is_unchanged() -> None:
    """The sweep is still the default; priority is the exception, not the rule."""
    fleet = _fleet(5)

    assert reconciliation_slice(fleet, today=TODAY, gaps={}) == reconciliation_slice(
        fleet, today=TODAY
    )
