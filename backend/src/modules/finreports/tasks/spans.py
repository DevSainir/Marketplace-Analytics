"""What a harvest run should walk, and for whom.

Two pure decisions lifted out of the harvest itself, because they are the part
that is reasoned about rather than executed: how far back a span reaches, and —
on the daily reconciliation pass — which single workspace gets it. Both are
answers to "what", and the module next door is entirely about "how".

They also share one subject the harvest does not: **what WB's quarter-hourly
settlement budget costs us in wall clock.** A span is priced in windows, a
window in a full refill of waiting, and the reconciliation slice exists only
because that price is paid per workspace, in sequence.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.core.logging import get_logger
from src.modules.finreports.constants import RECONCILE_LOOKBACK_DAYS
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


def walk_span(
    *, latest_settled: date | None, today: date, days: int, lookback_days: int = 0
) -> tuple[date, date]:
    """The settlement span one workspace's harvest should cover.

    Not the rolling ``days``-long window it used to be. That window was
    re-walked in full on every tick, which was affordable when it cost one
    request; at one request per week of it, and one request per quarter of an
    hour, a 28-day re-walk is an hour of somebody's harvest to re-read data
    already held.

    So the span starts at the last settled day rather than after it — the newest
    report's own week is re-read, which is where WB's amendments land — and
    falls back to the full ``days`` for a workspace that has never been
    harvested, which is the one case that legitimately needs a backfill.

    ``lookback_days`` is the reconciliation pass's whole mechanism: the span
    normally starts AT the watermark and therefore only ever moves forward,
    which is why a report WB starts serving for earlier days is invisible once
    the watermark has jumped past them. Extending the start backwards is what
    gives those days a second chance. See :data:`RECONCILE_LOOKBACK_DAYS`.

    Args:
        latest_settled: Last settlement day already harvested, or ``None``.
        today: Today in Moscow time.
        days: How far back a never-harvested workspace reaches.
        lookback_days: How far behind the watermark to re-read. Zero on the
            hourly path, where re-reading days already held would spend a
            quarter-of-an-hour WB request per week for nothing.

    Returns:
        The inclusive ``(date_from, date_to)`` span to walk.
    """
    date_to = today - timedelta(days=1)
    floor = date_to - timedelta(days=days)
    if latest_settled is None:
        return floor, date_to
    return max(floor, latest_settled - timedelta(days=lookback_days)), date_to


def reconciliation_slice(
    bundles: list[WorkspaceTokenBundle],
    *,
    today: date,
    gaps: dict[uuid.UUID, list[date]] | None = None,
) -> list[WorkspaceTokenBundle]:
    """The ONE workspace this reconciliation run re-reads.

    Measured on prod 2026-09-10 and this is why the pass is rationed rather than
    run across the fleet. Each extra window costs a full WB refill of *waiting*,
    not of work: the walk's two windows queued 633.8 s and 944.5 s, and the
    requests themselves took seconds. A three-window span is therefore ~45
    minutes for one workspace — and `_harvest_all_workspaces` walks workspaces
    in sequence, so the fleet cost is the sum, not the maximum. Five sellers
    would be three to four hours holding the platform-wide harvest lock, and it
    grows with every seller added.

    Running them concurrently is not the way out: a 10 000-row page costs about
    110 MB and the worker is capped at 768 MB, which is how the 2026-08-11 OOM
    happened.

    So one workspace a day, round-robin. The cost is flat in the size of the
    fleet, and each workspace comes round every ``len(bundles)`` days — which is
    safe only while that stays comfortably inside
    :data:`RECONCILE_LOOKBACK_DAYS`, because a day has to still be within the
    lookback when its turn arrives. The warning below is what makes that limit
    visible instead of silently losing days again.

    A workspace with a KNOWN gap jumps the queue. Without that, a detected hole
    would wait its turn — up to `len(bundles)` nights — and the detector would
    be reporting a fault the repair was in no hurry to reach. With it, a gap is
    walked the very next night, which is also what lets the alert on
    :data:`~src.core.observability.metrics.SETTLEMENT_GAP_DAYS` fire on a
    genuinely stuck gap rather than on one that is merely queued.

    Args:
        bundles: Every workspace eligible for this run.
        today: Today in Moscow time — the round-robin's only input, so the
            choice needs no stored cursor and no migration.
        gaps: Uncovered settlement days per workspace, when they have been
            surveyed. The oldest gap wins, so the day closest to ageing out of
            WB's reach is the one repaired first.

    Returns:
        A single-element list, or empty when there is nothing to walk.
    """
    if not bundles:
        return []
    surveyed = gaps or {}
    holed = [bundle for bundle in bundles if surveyed.get(bundle.workspace_id)]
    if holed:
        return [
            min(
                holed,
                key=lambda bundle: (
                    min(surveyed[bundle.workspace_id]),
                    str(bundle.workspace_id),
                ),
            )
        ]
    # Sorted so the rotation is stable across runs: the loader's order is a
    # query result, and a reshuffle would let one workspace be picked twice
    # running while another waited a fortnight.
    ordered = sorted(bundles, key=lambda bundle: str(bundle.workspace_id))
    if len(ordered) > RECONCILE_LOOKBACK_DAYS - 7:
        logger.warning(
            "finreports: %d workspaces on a %d-day lookback — a workspace now waits %d days "
            "for its turn, leaving too little margin for a back-dated report to still be "
            "inside the window when it arrives. Raise RECONCILE_LOOKBACK_DAYS or reconcile "
            "more than one workspace per run.",
            len(ordered),
            RECONCILE_LOOKBACK_DAYS,
            len(ordered),
        )
    return [ordered[today.toordinal() % len(ordered)]]


__all__ = ["reconciliation_slice", "walk_span"]
