"""One workspace's harvest, composed: walk, persist, warm, record.

This module owns no I/O of its own. It orders the phases — the paced settlement
walk (:mod:`src.modules.finreports.tasks.settlement`), the watermark write
(:mod:`src.modules.finreports.tasks.harvest.persistence`) and the post-harvest
warm-up (:mod:`src.modules.finreports.tasks.warmup`) — and it turns what they
report into the counts and the metrics the fleet walk and the alerts read.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.harvest import harvest_timer, record_harvest_outcome
from src.modules.finreports.tasks.harvest.persistence import advance_watermark
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import MissingReport, walk_settlement_reports
from src.modules.finreports.tasks.warmup import warm_settlement_rollup
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


#: Metric label for the weekly settlement walk. See the matching constant in
#: `monitoring/tasks/harvest.py` for why this is a name rather than a literal.
_HARVEST_FINANCE = "finreports.finance"


async def harvest_workspace(
    *, tokens: WorkspaceTokenBundle, reports: Sequence[MissingReport]
) -> dict[str, int]:
    """Harvest the settlement reports one workspace lacks, timed.

    The timer is the other half of the rows ``_harvest_workspace`` records.
    Rows alone are not enough: ``HarvestProducingNoRows`` joins ``on (harvest)``
    against ``harvest_duration_seconds_count``, so a harvest with no duration
    series is *structurally unalertable* — a run that wrote nothing reads as a
    run that never happened. The wrapper is what stops the two halves being
    recorded apart.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The settlement reports to fetch, oldest first — WB's own
            ids, from the freshness gate's list call.

    Returns:
        Whatever :func:`_harvest_workspace` returns, unchanged.
    """
    with harvest_timer(_HARVEST_FINANCE):
        return await _harvest_workspace(tokens=tokens, reports=reports)


async def _harvest_workspace(
    *, tokens: WorkspaceTokenBundle, reports: Sequence[MissingReport]
) -> dict[str, int]:
    """Fetch and persist one workspace's settlement reports.

    The body of :func:`harvest_workspace`, split out so the timer above wraps
    every path through it including the ones that raise.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The settlement reports to fetch, oldest first — WB's own
            ids, from the freshness gate's list call.

    Returns:
        ``finance`` — settlement rows written — and ``finance_windows_failed``,
        non-zero when part of the walk could not be fetched.
    """
    # `harvest_all_workspaces` walks every seller in one task, so the task-level
    # context names none of them. Binding here is what makes each line say which
    # seller it is about — and this walk is the single largest producer of log
    # volume in the service, so it is also where an unattributable line costs
    # the most.
    bind_workspace(tokens.workspace_id)

    # The settlement report, by report id, each batch committed as it lands
    # and each report booked in a transaction of its own — never one long
    # transaction: the walk waits for WB's token between requests (one a
    # minute on finance-api; once per quarter of an hour on the endpoint this
    # was written for), and waiting is the one thing an open transaction may
    # not do — PostgreSQL closes an idle one after 300 s. See
    # :mod:`src.modules.finreports.tasks.settlement` for what that cost before.
    walk = await walk_settlement_reports(
        tokens=tokens, reports=reports, build_ingestion=build_ingestion
    )
    if walk.completed_through is not None:
        await advance_watermark(
            workspace_id=tokens.workspace_id, completed_through=walk.completed_through
        )

    counts = {
        "finance": walk.rows,
        "finance_windows_failed": walk.windows_failed,
    }
    logger.info("finreports: harvested %s for %s.", counts, tokens.name)
    # The P&L reads the rollup, so the days this run touched are rebuilt now
    # rather than on the next page view.
    await warm_settlement_rollup(workspace_id=tokens.workspace_id, name=tokens.name)
    record_harvest_outcome(
        _HARVEST_FINANCE,
        counts=_row_counts(counts),
        failed_sources=_failed_sources(counts),
    )
    return counts


def _row_counts(counts: dict[str, int]) -> dict[str, int]:
    """Drop the failure reports, leaving only rows actually ingested.

    The `*_failed` keys are COUNTS OF FAILURES, not row counts, so adding them
    to `harvest_rows_processed_total` would inflate the one number that is
    supposed to answer "did this harvest do anything".
    """
    return {key: value for key, value in counts.items() if not key.endswith("_failed")}


def _failed_sources(counts: dict[str, int]) -> tuple[str, ...]:
    """Name every source this run could not fully harvest."""
    return ("finance",) if counts["finance_windows_failed"] else ()


__all__ = ["harvest_workspace"]
