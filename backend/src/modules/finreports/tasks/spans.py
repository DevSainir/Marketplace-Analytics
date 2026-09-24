"""What a harvest run should walk, and for whom.

Three pure decisions lifted out of the harvest itself, because they are the
part that is reasoned about rather than executed: where the settlement history
is closed through, how far back a span reaches, and — on the daily
reconciliation pass — which single workspace gets it. All three are answers to
"what", and the module next door is entirely about "how".

They also share one subject the harvest does not: **what WB's settlement budget
costs us in wall clock.** A span is priced in windows, a window in a full
refill of waiting, and the reconciliation slice exists only because that price
is paid per workspace, in sequence. The refill was a quarter of an hour when
this was written and is a minute on finance-api (2026-09-22); the slice stands
because the fleet-wide lock is still held for the whole of it.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.core.logging import get_logger
from src.modules.finreports.constants import RECONCILE_LOOKBACK_DAYS
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


def settlement_frontier(*, watermark: date | None, covered_through: date | None) -> date | None:
    """How far the settlement history is **actually** closed, for the gate and the span.

    The third answer to "what", and the one the other two were quietly getting
    wrong in opposite directions. Two dates claim to say where the history ends
    and neither can be trusted alone:

    * ``covered_through`` — ``max(financial_report.date_to)``, the period WB
      *states*. Written from the first page that lands, so a week walked one day
      deep already claims all six. Trusting it skipped five of six days on
      2026-09-07.
    * ``watermark`` — the last day of the walk's completed prefix. Honest about
      what was *asked*, and that is exactly its flaw: a window WB answered
      **empty** completes like any other. WB forms a week's report the day
      *after* the week ends, so every Sunday-night tick asks about the open week,
      is told nothing, and certifies the whole week as settled. On 2026-09-14
      that is precisely what had happened to three of five workspaces: watermark
      13.09, newest report ending 06.09, report 985672101 (07.09-13.09, formed
      14.09) published into a window nothing would ever ask about again. The
      hourly gate answered «settled through 13.09 — nothing newer can exist yet»
      to every tick, «Обновить» included.

    So: **the earlier of the two**. A day is closed only when it was both asked
    about completely and answered with a report that covers it. Each date is a
    ceiling on the other, which is what makes both failures unrepresentable
    rather than alternately fixed.

    ``covered_through`` of ``None`` — a workspace holding no report at all —
    constrains nothing and leaves the watermark standing. There is no coverage
    to be behind, and the alternative is a full backfill span re-walked every
    hour for a seller WB has published nothing for; a first report arriving late
    for one of those is the reconciliation pass's job, as it is for any other
    back-dated report.

    Args:
        watermark: Last day of the walk's completed prefix, or ``None`` when no
            window has ever completed.
        covered_through: Last day any harvested report's period covers, or
            ``None`` when this workspace holds no reports.

    Returns:
        The day the history is closed through, or ``None`` when nothing closes
        it — which every caller must read as "never harvested", i.e. as a reason
        to walk rather than to skip.
    """
    if watermark is None:
        return covered_through
    if covered_through is None:
        return watermark
    return min(watermark, covered_through)


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


__all__ = ["reconciliation_slice", "settlement_frontier"]
