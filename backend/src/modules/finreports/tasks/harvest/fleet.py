"""The fleet walk: which workspaces get harvested this tick, and over what span.

The per-workspace half is :mod:`src.modules.finreports.tasks.harvest.workspace`;
this module decides who it is called for. That decision is the whole of the
hourly cost — the freshness gate, the gap survey, the reconciliation slice and
the single-flight lock are all here, and each of them exists because a tick that
walks everybody costs the fleet's WB budget.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import date, timedelta
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.locks import single_flight
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.timeutils import moscow_today
from src.modules.finreports.constants import (
    HARVEST_LOCK_KEY,
    HARVEST_LOCK_TTL_SECONDS,
    SETTLEMENT_LIST_WINDOW_DAYS,
)
from src.modules.finreports.repos import (
    FinancialReportRepository,
    SettlementWatermarkRepository,
)
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessRecordStore,
)
from src.modules.finreports.tasks.daily_tail import tail_one_workspace
from src.modules.finreports.tasks.freshness import (
    check_freshness,
    freshness_record_store,
    settlement_blocked_for,
    verdict_from_walk,
)
from src.modules.finreports.tasks.gaps import survey_settlement_gaps
from src.modules.finreports.tasks.harvest.due import sellers_owed_a_report
from src.modules.finreports.tasks.harvest.ledger import (
    record_wb_totals,
    refresh_archive_totals,
    reports_to_re_walk,
)
from src.modules.finreports.tasks.harvest.workspace import harvest_workspace
from src.modules.finreports.tasks.publication_log import log_first_listings
from src.modules.finreports.tasks.repair import gap_repair_due
from src.modules.finreports.tasks.spans import (
    settlement_frontier,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)


#: Workspaces harvested at once by a fleet tick.
#:
#: Three, and the bound is memory rather than WB: each one streams settlement
#: pages into its own session against a 768 MiB cgroup. What it hides is the
#: pacing — a tick waits about a minute per seller for its second `list` token,
#: and those waits are independent because WB meters per seller account.
_FLEET_CONCURRENCY = 3

#: Zeroed result shape, so a locked-out or empty run reports the same keys a
#: full one does and callers never have to guess whether a key is missing or 0.
#: ``workspaces_failed`` counts sellers whose harvest raised: one seller's
#: failure is isolated and counted rather than taking the fleet tick down.
_EMPTY_TOTALS: dict[str, int] = {
    "finance": 0,
    "baselines": 0,
    "penalties": 0,
    "measurements": 0,
    "storage_windows_failed": 0,
    "finance_windows_failed": 0,
    "baselines_failed": 0,
    "workspaces_skipped": 0,
    "skipped_locked": 0,
    "daily_tail_reports": 0,
    "daily_tail_rows": 0,
    "daily_tail_failed": 0,
    "workspaces_failed": 0,
}


async def harvest_all_workspaces(
    *, workspace_id: uuid.UUID | None = None, reconcile: bool = False, gated: bool = False
) -> dict[str, int]:
    """Harvest every workspace with a WB report it does not hold.

    Scheduled ticks run ``gated``, on the hours a report can arrive, and only
    walk the sources for a workspace WB has published an
    unharvested report for — see :mod:`.freshness` for what that costs and what
    it deliberately does not catch. ``workspaces_skipped`` reports how many were
    gated out, so a run that harvested nothing is distinguishable from one that
    never asked.

    Only one run at a time: the walk below is minutes long and the schedule
    fires every hour, so without the lock a run that found a new report would
    still be pacing its storage windows when the next tick started a second copy
    against the same ~1 req/min WB surfaces. ``skipped_locked`` is 1 when this
    call was the one turned away.

    Args:
        workspace_id: Restrict the walk to one workspace. The hourly schedule
            omits it and sweeps the fleet; the «Обновить» button passes the
            caller's own workspace, because a request from one tenant must not
            spend the WB budget — or the wall-clock — of every other tenant on
            the platform.
        reconcile: Re-read :data:`RECONCILE_LOOKBACK_DAYS` behind the watermark
            and walk **whatever the freshness gate says**. Both halves are
            required and neither is useful alone: the span is what reaches days
            the forward-only walk has left behind, and ignoring the gate is what
            lets it run at all, since the gate's whole job is to answer "nothing
            newer exists" — which is true, and beside the point, exactly when a
            back-dated report is the thing being looked for. Once a day; see
            :func:`_harvest_all_workspaces`.
        gated: Ask WB only about sellers still owed a report today, judged from
            our own tables (:mod:`.due`). Scheduled ticks set it; «Обновить»,
            a first harvest and the nightly pass do not.

    Returns:
        Row counts per source, summed over whichever workspaces were walked.
    """
    async with single_flight(
        HARVEST_LOCK_KEY, ttl_seconds=HARVEST_LOCK_TTL_SECONDS, redis=get_redis()
    ) as acquired:
        if not acquired:
            logger.info("finreports: a harvest is already in flight — skipping this tick.")
            return dict(_EMPTY_TOTALS, skipped_locked=1)
        return await _harvest_all_workspaces(
            workspace_id=workspace_id, reconcile=reconcile, gated=gated
        )


async def _harvest_all_workspaces(
    *, workspace_id: uuid.UUID | None, reconcile: bool = False, gated: bool = False
) -> dict[str, int]:
    """Walk every eligible workspace. See :func:`harvest_all_workspaces`.

    The reconciliation pass exists because the ordinary one could only ever move
    forward. The date-span walk this was written against (`_walk_span`, gone
    with the endpoint) started at the watermark and the watermark jumped to the
    newest report's stated end, so the moment a weekly report landed, every
    earlier day left the reachable window for good. WB does not publish in
    that order — it forms single-day supplementary reports and starts serving
    their rows days later — and on 2026-08-31 that cost every workspace a day of
    settlement: report 983241109 was formed 09-01, was still unserved on 09-06
    (80 probes, every one of them a 204), and by the time WB served it the watermark had moved
    to 09-06 and nothing would ever ask again.
    """
    today = moscow_today()
    async with AsyncSessionLocal() as session:
        bundles = await _bundles_to_walk(session, workspace_id=workspace_id)
        # BOTH dates, and the earlier of them — see `settlement_frontier`, which
        # is where the reasoning lives. Neither alone is a safe answer to "where
        # does this history end": `max(header.date_to)` over-claims a week walked
        # one day deep, and the walk's own watermark over-claims every week WB
        # has not published yet, because a window answered EMPTY completes like
        # any other. The second is how the 07.09-13.09 report went unharvested by
        # three of five workspaces while the gate answered «settled through
        # 13.09 — nothing newer can exist yet» to every tick.
        watermark_repo = SettlementWatermarkRepository(session)
        report_repo = FinancialReportRepository(session)
        settled = {
            bundle.workspace_id: settlement_frontier(
                watermark=await watermark_repo.get(workspace_id=bundle.workspace_id),
                covered_through=await report_repo.latest_settled_date(
                    workspace_id=bundle.workspace_id
                ),
            )
            for bundle in bundles
        }
        # The reports we hold. WB's own list is what they are compared against
        # — ids, not periods, because an id cannot be ambiguous the way a
        # period can: a report served out of order, one WB splits at a month
        # end and a re-issued one are all just ids.
        #
        # A report that does not add up to WB's total is NOT subtracted here,
        # and was until 2026-09-26 — which re-fetched it every fifteen minutes.
        # That paid for itself only while a header could be written over half
        # a report; since the header is written after the last page, a fetch
        # that dies part-way leaves no header and is simply still missing. A
        # report fetched whole that still disagrees will disagree on every
        # re-fetch: it is our arithmetic or WB's restatement, not the download.
        # So it goes to the alert and to the nightly pass, once a day.
        held = {
            bundle.workspace_id: await report_repo.report_ids_since(
                workspace_id=bundle.workspace_id,
                since=today - timedelta(days=SETTLEMENT_LIST_WINDOW_DAYS),
            )
            for bundle in bundles
        }
    # Surveyed on EVERY tick, not only the nightly one: the survey is SQL and
    # costs no WB request, so there is no reason to learn about a hole only when
    # its turn comes round. Rationing is about the walk, not about knowing.
    gaps = await survey_settlement_gaps(bundles, today=today, announce=reconcile)
    if reconcile:
        # Every seller, every night. It was one a night, round-robin, when a
        # fortnight's re-walk was three quarter-hour windows of the old
        # endpoint; on finance-api it is a few one-a-minute requests per seller,
        # three sellers at a time, so rationing only delayed each seller's turn
        # by the size of the fleet.
        repairing = {bundle.workspace_id for bundle in bundles}
    else:
        repairing = await gap_repair_due(bundles, today=today, gaps=gaps)
    skipped = 0
    if gated:
        # A seller holding yesterday and the last closed period has nothing left
        # to come today, so no request is spent asking. A hole just chosen for
        # repair is walked regardless.
        ids = [bundle.workspace_id for bundle in bundles]
        owed = repairing | await sellers_owed_a_report(ids, today=today)
        skipped = sum(bundle.workspace_id not in owed for bundle in bundles)
        bundles = [bundle for bundle in bundles if bundle.workspace_id in owed]
    records: FreshnessRecordStore = freshness_record_store()
    # Several sellers at once: a tick waits a minute per seller for its second
    # `list` token, WB meters per seller account, so the waits overlap. Bounded
    # by memory (see `_FLEET_CONCURRENCY`), not by WB.
    results = await _gather_bounded(
        [
            _isolated(
                bundle.name,
                _harvest_one(
                    bundle=bundle,
                    settled=settled,
                    held=held,
                    today=today,
                    reconcile=reconcile,
                    repairing=repairing,
                    records=records,
                ),
            )
            for bundle in bundles
            if bundle.finance
        ],
        limit=_FLEET_CONCURRENCY,
    )
    totals = dict(_EMPTY_TOTALS, workspaces_skipped=skipped)
    for counts in results:
        for key, value in counts.items():
            totals[key] += value
    return totals


async def _gather_bounded(
    coroutines: list[Coroutine[Any, Any, dict[str, int]]], *, limit: int
) -> list[dict[str, int]]:
    """Run the coroutines with at most ``limit`` in flight, keeping their order.

    A plain ``gather`` would start every seller at once; a plain loop starts one.
    Neither is right — see the caller for what the bound is sized against.

    Args:
        coroutines: One per workspace, each returning its counts fragment.
        limit: Most to have running at any moment.

    Returns:
        Their results, in the order given.
    """
    guard = asyncio.Semaphore(limit)

    async def _one(coroutine: Coroutine[Any, Any, dict[str, int]]) -> dict[str, int]:
        async with guard:
            return await coroutine

    return list(await asyncio.gather(*(_one(coroutine) for coroutine in coroutines)))


async def _isolated(name: str, work: Coroutine[Any, Any, dict[str, int]]) -> dict[str, int]:
    """Run one seller's harvest so that its failure stays its own.

    Concurrent sellers share one task, and a bare ``gather`` lets the first
    exception out while the others are mid-walk: the task disposes of the engine
    under them, and autoretry re-runs the whole fleet for one seller's fault. So
    a seller that raises is logged — at ERROR, which reaches Sentry — and counted
    in ``workspaces_failed``, and the next tick asks for it again.

    The soft time limit is re-raised: it is the task's deadline, not this
    seller's failure, and swallowing it would run the fleet on into the hard kill.

    Args:
        name: The seller, for the log line.
        work: Its harvest, not yet started.

    Returns:
        The seller's counts, or an empty fragment marking it failed.
    """
    try:
        return await work
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("finreports: harvest failed for %s; the rest of the fleet goes on.", name)
        return dict(_EMPTY_TOTALS, workspaces_failed=1)


async def _harvest_one(
    *,
    bundle: WorkspaceTokenBundle,
    settled: dict[uuid.UUID, date | None],
    held: dict[uuid.UUID, set[int]],
    today: date,
    reconcile: bool,
    repairing: set[uuid.UUID],
    records: FreshnessRecordStore,
) -> dict[str, int]:
    """Harvest one workspace: the settled report, then the provisional tail.

    The body of the fleet loop, extracted so several sellers can be in flight at
    once. Everything it touches is per workspace — its own WB tokens, its own
    sessions, its own Redis keys — so the only thing the caller has to do is add
    up what each returns.

    Args:
        bundle: The workspace's decrypted WB credentials.
        settled / held: The frontier and the report ids already on file, read
            once for the whole fleet before any of this runs.
        today: Today in Moscow time.
        reconcile: Whether this is the pass that re-reads behind the coverage.
        repairing: Workspaces an hourly tick should walk regardless of the gate.
        records: Where the freshness verdict is written.

    Returns:
        A counts fragment shaped like :data:`_EMPTY_TOTALS`.
    """
    totals = dict(_EMPTY_TOTALS)
    verdict, missing, listed = await check_freshness(
        tokens=bundle,
        latest_settled=settled[bundle.workspace_id],
        held=held[bundle.workspace_id],
        today=today,
        # Read from the shared Redis bucket, not from WB: asking WB whether
        # WB will accept a request is the one thing that cannot be done
        # here, and a peek takes no token.
        blocked_for=await settlement_blocked_for(bundle),
    )
    # WB's own totals for every report it named, onto the ones we already hold.
    # Free — the list was already fetched for the gate above — and an UPDATE
    # rather than an upsert, so a report WB has listed and we have NOT taken
    # cannot be created here and counted as held (see `refresh_wb_totals`).
    #
    # It runs on every tick rather than only when something is missing, because
    # WB restates a settled week for up to a fortnight and the totals are the
    # only figure the P&L can be checked against that is not our own
    # arithmetic. A tick that finds nothing new still finds newer numbers.
    await record_wb_totals(workspace_id=bundle.workspace_id, listed=listed)
    # And when the API first named each report — only off an answer WB gave.
    if verdict and verdict.outcome in (FreshnessOutcome.UP_TO_DATE, FreshnessOutcome.WB_HAS_NEW):
        await log_first_listings(
            workspace_id=bundle.workspace_id,
            name=bundle.name,
            period="weekly",
            listed=listed,
            held=held[bundle.workspace_id],
        )
    # The one remaining way to learn nothing: no «Финансы» token, so no
    # request was made and none can be. Recording a verdict here would
    # claim a check that cannot happen. (The caller skips such workspaces
    # already; this is the gate saying the same thing for any other caller.)
    if verdict is None:
        return dict(totals, workspaces_skipped=1)
    # Recorded BEFORE the branch, so "asked WB and there was nothing" leaves
    # the same trace as "asked WB and harvested". Recording only on the
    # harvesting path would leave a quiet week and a dead worker looking
    # identical on the page — which is the whole bug this closes.
    await records.put(bundle.workspace_id, verdict)
    # The gate answers "is there anything NEWER", which is the wrong
    # question for a back-dated report and answers "no" precisely when one
    # is what we are looking for. A reconciliation pass therefore walks
    # regardless — that is the point of it — and so does an hourly tick for
    # a workspace the survey can see a hole in. Both are the same statement:
    # a day we know is missing is not a day to ask a forward question about.
    thorough = reconcile or bundle.workspace_id in repairing
    # A standing block outranks «thorough», and it is the only verdict that
    # does. Everything else `thorough` overrides is a claim about the DATA
    # — «nothing newer exists» — and overriding it is the whole point of a
    # reconciliation pass, which exists to ask about days the forward
    # question cannot see. `RATE_BLOCKED` is a claim about the CHANNEL:
    # WB has refused, and walking anyway does not fetch the missing day, it
    # lengthens the refusal. It stops the daily tail below for the same
    # reason. The router refuses a click before it ever enqueues; this is the
    # same rule for the path that has no router in front of it.
    if verdict.outcome is FreshnessOutcome.RATE_BLOCKED:
        return dict(totals, workspaces_skipped=1)
    if verdict.should_harvest or thorough:
        # A thorough pass re-asks for reports it already holds — that is what
        # it is for. WB's list gives the ids; the lookback decides how many of
        # the held ones to re-walk, since an amendment to a week on file is
        # invisible to «which ids am I missing».
        if reconcile:
            await refresh_archive_totals(tokens=bundle, today=today)
        if thorough:
            # The fortnight's re-walk and every short report, whether or not
            # WB also has something new — a new report no longer postpones them.
            owed = {report.report_id: report for report in missing}
            for report in await reports_to_re_walk(
                report_repo_for=bundle.workspace_id, today=today
            ):
                owed.setdefault(report.report_id, report)
            missing = tuple(sorted(owed.values(), key=lambda report: report.date_to))
        if missing:
            counts = await harvest_workspace(tokens=bundle, reports=missing, on_date=today)
            for key, value in counts.items():
                totals[key] += value
            # And recorded AGAIN, from what the walk found. The walk asks WB
            # about the same days the probe did, so a completed one is strictly
            # better evidence — and throwing it away is the same discard bug one
            # level up.
            #
            # It is not hypothetical. On 2026-09-09 the probe hit the settlement
            # endpoint's 15-minute block and 429'd, the gate failed open, and
            # seven minutes later the walk asked the same window and got 204 —
            # proof there was nothing new. The page kept showing «не удалось
            # спросить» over a statement that had just been confirmed complete.
            if not counts.get("finance_windows_failed"):
                await records.put(
                    bundle.workspace_id,
                    await verdict_from_walk(
                        workspace_id=bundle.workspace_id,
                        settled_before=settled[bundle.workspace_id],
                        date_from=missing[0].date_to,
                        date_to=missing[-1].date_to,
                    ),
                )
        else:
            # Nothing to fetch, and on the new surface that is a complete
            # statement rather than a reason to walk blindly. A failed list
            # (`PROBE_FAILED`) lands here too: without WB's answer there are no
            # report ids to ask for, so the honest move is to record that we
            # could not ask and let the next tick try.
            totals["workspaces_skipped"] += 1
    else:
        totals["workspaces_skipped"] += 1

    # The provisional daily tail, after this workspace's settled walk rather
    # than beside it.
    #
    # Settled first is load-bearing rather than tidy: the weekly walk moves the
    # frontier, and the tail covers only what lies past it — so the other order
    # would spend a request per day on days the weekly report was about to
    # settle, and leave those rows carrying a provisional `report_id` until
    # something overwrote them.
    #
    # Unconditional, unlike the walk above: «WB has nothing newer weekly» is
    # exactly when yesterday is only reachable through the daily lane.
    tail = await tail_one_workspace(tokens=bundle, today=today)
    totals["daily_tail_reports"] += tail["reports"]
    totals["daily_tail_rows"] += tail["rows"]
    totals["daily_tail_failed"] += tail["reports_failed"]
    return totals


async def _bundles_to_walk(
    session: AsyncSession, *, workspace_id: uuid.UUID | None
) -> list[WorkspaceTokenBundle]:
    """Load credentials for the workspaces this run is allowed to touch.

    A scoped run loads exactly one bundle rather than loading every tenant's and
    filtering: the fleet loader decrypts each workspace's WB tokens, and one
    tenant pressing «Обновить» is no reason to touch the others' secrets.

    Args:
        session: An open session (the caller owns the transaction).
        workspace_id: The single workspace to walk, or ``None`` for the fleet.

    Returns:
        The bundles to walk — empty when a scoped workspace no longer exists.
    """
    if workspace_id is None:
        return list(await load_workspace_token_bundles(session))
    bundle = await load_workspace_token_bundle(session, workspace_id)
    return [bundle] if bundle is not None else []


__all__ = ["harvest_all_workspaces"]
