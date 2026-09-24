"""One workspace's harvest, composed: read, walk, persist, warm, record.

This module owns no I/O of its own. It orders the phases — the WB read
(:mod:`src.modules.finreports.tasks.harvest.sources`), the paced settlement walk
(:mod:`src.modules.finreports.tasks.settlement`), the two writes
(:mod:`src.modules.finreports.tasks.harvest.persistence`) and the post-harvest
warm-ups (:mod:`src.modules.finreports.tasks.warmup`) — and it turns what they
report into the counts and the metrics the fleet walk and the alerts read.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from src.core.celery_app import celery_app
from src.core.logcontext import bind_workspace
from src.core.logging import get_logger
from src.core.observability.harvest import harvest_timer, record_harvest_outcome
from src.modules.finreports.tasks.harvest.persistence import (
    advance_watermark,
    persist_sources,
)
from src.modules.finreports.tasks.ingestion_factory import build_ingestion
from src.modules.finreports.tasks.settlement import MissingReport, walk_settlement_reports
from src.modules.finreports.tasks.warmup import warm_settlement_rollup
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)


#: Metric label for the weekly settlement walk. See the matching constant in
#: `monitoring/tasks/harvest.py` for why this is a name rather than a literal.
_HARVEST_FINANCE = "finreports.finance"


async def harvest_workspace(
    *, tokens: WorkspaceTokenBundle, reports: Sequence[MissingReport], on_date: date
) -> dict[str, int]:

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
        on_date: Snapshot day for the baseline (Moscow time).

    Returns:
        Whatever :func:`_harvest_workspace` returns, unchanged.
    """
    with harvest_timer(_HARVEST_FINANCE):
        return await _harvest_workspace(tokens=tokens, reports=reports, on_date=on_date)


async def _harvest_workspace(
    *, tokens: WorkspaceTokenBundle, reports: Sequence[MissingReport], on_date: date
) -> dict[str, int]:
    """Fetch and persist one workspace's finreports sources.

    The body of :func:`harvest_workspace`, split out so the timer above wraps
    every path through it including the ones that raise.

    Args:
        tokens: The workspace's decrypted WB credentials.
        reports: The settlement reports to fetch, oldest first — WB's own
            ids, from the freshness gate's list call.
        on_date: Snapshot day for the baseline (Moscow time).

    Returns:
        ``penalties``), plus two failure reports: ``storage_windows_failed``,
        non-zero when the window is only partly covered and the storage claim
        is therefore understated, and ``baselines_failed``, 1 when today's
    """
    # `harvest_all_workspaces` walks every seller in one task, so the task-level
    # context names none of them. Binding here is what makes each line say which
    # seller it is about — and this walk is the single largest producer of log
    # volume in the service, so it is also where an unattributable line costs
    # the most (register P2.2).
    bind_workspace(tokens.workspace_id)
    # The reports' whole span, not their closing days: `date_to` alone is one
    span_from = min((r.date_from or r.date_to for r in reports), default=on_date)
    span_to = max((r.date_to for r in reports), default=on_date)

    # The settlement report, by report id, each batch committed as it lands
    # and each report booked in a transaction of its own. It is NOT part of the
    # row commit below: the walk waits for WB's token between requests (one a
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
        **await persist_sources(sources=sources, workspace_id=tokens.workspace_id, on_date=on_date),
        "storage_windows_failed": len(sources.storage_failures),
        "finance_windows_failed": walk.windows_failed,
        "baselines_failed": int(sources.baseline_failed),
    }
    logger.info("finreports: harvested %s for %s.", counts, tokens.name)
    # Unconditional, unlike the internal-only warm-up below: P&L reads the rollup.
    await warm_settlement_rollup(workspace_id=tokens.workspace_id, name=tokens.name)
    if tokens.internal_features:
        # it would re-price an empty ledger and cache an answer no request can
        # ask for.
        #
        # **Enqueued, not awaited, since 2026-09-19**, and the reason is the
        # whole point of calling it best-effort. Awaited, it was not
        # (~269 MB, measured), and on a worker whose floor had ratcheted that
        # is over the cgroup cap. The kernel does not care that the caller
        # meant it to be optional — it killed the child, and with it the
        # `record_harvest_outcome` below and every workspace still queued
        # behind this one. Twenty-one hourly harvests died that way between
        # 09-18 01:56 and 09-19 01:56, and the P&L went six days stale.
        #
        # A separate task cannot do that. It dies alone, it is acknowledged
        # rather than requeued, and `celery_worker_lost_total` names it instead
        # of blaming the harvest.
        celery_app.send_task(
            kwargs={"workspace_id": str(tokens.workspace_id), "name": tokens.name},
        )
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
    if counts["finance_windows_failed"]:
        failed = (*failed, "finance")
    if counts["baselines_failed"]:
        # Named here so a 403 on the Content surface shows up as a withheld
        # source next to the others, rather than only as a log line nobody
        # reads: `baselines: 0` alone reads as "nothing to snapshot".
        failed = (*failed, "baselines")
    return failed


__all__ = ["harvest_workspace"]
