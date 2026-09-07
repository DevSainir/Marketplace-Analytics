"""One workspace, everything WB will tell us about it.

Before this module the word "refresh" meant three different amounts of data
depending on which button produced it. «Обновить» fetched funnel, stocks,
advertising and prices; it skipped the sale/return feed, so «Выкупы, ₽» and
«Процент выкупа» kept yesterday's values behind a green tick. The buyout-cohort
pass — the thing that actually matures «Процент выкупа» — ran only on its own
07:00 MSK schedule and was reachable from no button at all. A seller pressing
«Обновить» and watching the buyout column not move was seeing the system work
as designed, which is the worst kind of correct.

This is now the single body behind every refresh. The interactive
``monitoring.harvest_sku_window`` and the automatic
``monitoring.discover_workspace`` both call it, so the two cannot drift apart
again, and "refreshed" means one thing.

**Cohorts are a source, not a precondition.** They are the most expensive thing
here — 22 sequential rate-limited requests, ~7 minutes — and the least urgent,
since a cohort keeps maturing for about three weeks. So a cohort failure is
counted as a withheld source and reported to the UI beside every other one,
exactly as a withheld funnel is; it never voids a harvest whose other sources
succeeded. That is the same lesson ``discovery.py`` records about the Content
API, and it is written down twice because it was learned twice.
"""

from __future__ import annotations

from datetime import date

from src.core.logging import get_logger
from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.services import claim_cohort_pass
from src.modules.monitoring.tasks.cohorts import COHORT_REFRESH_DAYS, _refresh_workspace_cohorts
from src.modules.monitoring.tasks.harvest import HarvestOutcome, _harvest_sku_window
from src.modules.workspaces.contract import WorkspaceTokenBundle

logger = get_logger(__name__)

#: Label the cohort pass reports under when WB withholds it. Matches the
#: naming of the sources in ``harvest.py`` («sales-funnel», «stocks-fbs») so the
#: SPA's «WB не отдал…» list reads as one vocabulary rather than two.
COHORT_SOURCE_LABEL = "funnel-cohorts"


async def refresh_workspace_data(
    *,
    tokens: WorkspaceTokenBundle,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    cards: list[WBCard] | None = None,
    cohort_days: int = COHORT_REFRESH_DAYS,
    include_cohorts: bool = True,
) -> HarvestOutcome:
    """Refresh every WB fact this workspace has, in one pass.

    Runs the SKU-window harvest **including** the sale/return feed, then the
    buyout-cohort pass unless a recent one already covers this workspace.

    The sale feed is included here where the interactive path used to skip it.
    WB serves it account-wide only (``supplier/sales`` takes a ``dateFrom`` and
    no SKU filter) on the harshest limiter it exposes — measured live as a
    39-second 429 backoff. That cost is real and is the reason it was excluded;
    it is accepted now because the alternative was a refresh that silently left
    two of the columns a seller reads most standing still.

    Args:
        tokens: The workspace's decrypted WB credentials.
        nm_ids: The SKUs to harvest funnel, stock and advertising for.
        date_from: Inclusive window start (Moscow time).
        date_to: Inclusive window end (Moscow time).
        cards: Content-API cards to refresh the catalogue with, when the caller
            already fetched them (the discovery flow does).
        cohort_days: How far back to re-read order-date cohorts.
        include_cohorts: Whether to run the cohort pass at all. The nightly
            fleet harvest passes ``False``: ``monitoring.refresh_buyout_cohorts``
            already sweeps every workspace an hour later on its own schedule, so
            running the pass here too would spend 22 rate-limited requests per
            workspace to write rows that pass is about to write again. Every
            path a person can trigger passes ``True`` — for them the hour's wait
            is the whole problem.

    Returns:
        The harvest's row counts, plus ``cohort_rows``, plus every source WB
        withheld. ``cohort_rows`` is 0 both when the pass was skipped as
        redundant and when it genuinely found nothing — the difference is in
        ``failed_sources``, which is where the UI already looks.
    """
    outcome = await _harvest_sku_window(
        tokens=tokens,
        nm_ids=nm_ids,
        date_from=date_from,
        date_to=date_to,
        cards=cards,
        include_sales=True,
    )
    counts = dict(outcome.counts)
    failed = list(outcome.failed_sources)

    counts["cohort_rows"] = 0
    if not include_cohorts:
        return HarvestOutcome(counts=counts, failed_sources=tuple(failed))
    if not await claim_cohort_pass(tokens.workspace_id):
        logger.info(
            "Cohorts for workspace '%s' were refreshed recently; skipping the pass.",
            tokens.name,
        )
        return HarvestOutcome(counts=counts, failed_sources=tuple(failed))

    try:
        counts["cohort_rows"] = await _refresh_workspace_cohorts(tokens, cohort_days)
    except Exception as exc:
        # Broad on purpose, and NOT re-raised. Every other source in this pass
        # has already been persisted by the harvest above; letting the cohort
        # surface fail the task would throw away a completed funnel, stock and
        # advertising harvest because the slowest, least urgent source timed
        # out. The seller is told which source was withheld instead.
        logger.warning(
            "Cohort pass failed for workspace '%s' (%s); the rest of the refresh stands.",
            tokens.name,
            exc,
        )
        failed.append(COHORT_SOURCE_LABEL)

    return HarvestOutcome(counts=counts, failed_sources=tuple(failed))
