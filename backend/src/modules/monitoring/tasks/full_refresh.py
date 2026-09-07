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

from collections.abc import Callable
from datetime import date

from celery import Task

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

#: Reports how far along a refresh is: ``(stage, percent, message)``. The
#: message is Russian and user-facing — it is rendered verbatim under the
#: «Обновить» button, so it says what is happening rather than which function
#: is running.
ProgressReporter = Callable[[int, int, str], None]

#: The two stages a person waits through, in order.
STAGE_HARVEST = 1
STAGE_COHORTS = 2
TOTAL_STAGES = 2

#: Share of the bar the first stage owns. Not 50: stage one is seconds to a
#: minute and stage two is ~7 minutes, so an even split would park the bar at
#: half for the whole visible wait. Forty is roughly honest about the time and
#: still gives the first stage a satisfying jump.
_HARVEST_SHARE = 40

#: What the seller reads while each stage runs. Deliberately naming the DATA
#: rather than the system: «воронка» and «проценты выкупа» are the columns they
#: are looking at, and «этап 2 из 2» alone tells them nothing about whether the
#: number they came for has arrived yet.
MSG_HARVEST = "Собираем рекламу, воронку, остатки и цены…"
MSG_COHORTS = "Реклама, воронка, остатки и цены собраны. Считаем проценты выкупа…"
MSG_DONE = "Данные Wildberries обновлены."


async def refresh_workspace_data(
    *,
    tokens: WorkspaceTokenBundle,
    nm_ids: list[int],
    date_from: date,
    date_to: date,
    cards: list[WBCard] | None = None,
    cohort_days: int = COHORT_REFRESH_DAYS,
    include_cohorts: bool = True,
    progress: ProgressReporter | None = None,
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
        progress: Where to report stage and percentage, when someone is
            watching. The scheduled passes leave it ``None``: nothing polls
            them, and a task that publishes progress no one reads still pays
            Celery a result-backend write per update.

    Returns:
        The harvest's row counts, plus ``cohort_rows``, plus every source WB
        withheld. ``cohort_rows`` is 0 both when the pass was skipped as
        redundant and when it genuinely found nothing — the difference is in
        ``failed_sources``, which is where the UI already looks.
    """
    if progress is not None:
        progress(STAGE_HARVEST, 0, MSG_HARVEST)

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

    # Stage one is COMMITTED by now — ``_harvest_sku_window`` owns its own
    # transaction and closed it. That is what lets the SPA redraw the table on
    # this signal instead of waiting out the cohort pass: the funnel, stock,
    # advertising and price rows are durable, not pending.
    counts["cohort_rows"] = 0
    if not include_cohorts:
        if progress is not None:
            progress(TOTAL_STAGES, 100, MSG_DONE)
        return HarvestOutcome(counts=counts, failed_sources=tuple(failed))
    if progress is not None:
        progress(STAGE_COHORTS, _HARVEST_SHARE, MSG_COHORTS)
    if not await claim_cohort_pass(tokens.workspace_id):
        logger.info(
            "Cohorts for workspace '%s' were refreshed recently; skipping the pass.",
            tokens.name,
        )
        if progress is not None:
            progress(TOTAL_STAGES, 100, MSG_DONE)
        return HarvestOutcome(counts=counts, failed_sources=tuple(failed))

    def _on_day(done: int, total: int) -> None:
        if progress is None:
            return
        span = 100 - _HARVEST_SHARE
        progress(STAGE_COHORTS, _HARVEST_SHARE + round(span * done / total), MSG_COHORTS)

    try:
        counts["cohort_rows"] = await _refresh_workspace_cohorts(tokens, cohort_days, _on_day)
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

    if progress is not None:
        progress(TOTAL_STAGES, 100, MSG_DONE)
    return HarvestOutcome(counts=counts, failed_sources=tuple(failed))


def celery_progress(task: Task[object, object]) -> ProgressReporter:
    """Publish refresh progress on a task's own Celery state.

    ``update_state`` writes a custom ``PROGRESS`` state with a meta payload,
    which ``AsyncResult.info`` hands back to the status endpoint. Using the
    task's own state rather than a side channel means the progress and the
    result expire together and can never disagree about which run they describe.

    Args:
        task: The bound task instance to publish against.

    Returns:
        A reporter the refresh body can call at each stage boundary.
    """

    def _report(stage: int, percent: int, message: str) -> None:
        task.update_state(
            state="PROGRESS",
            meta={
                "stage": stage,
                "stages": TOTAL_STAGES,
                "percent": percent,
                "message": message,
            },
        )

    return _report
