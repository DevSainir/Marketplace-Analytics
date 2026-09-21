"""The fleet walk: which workspaces get harvested this tick, and over what span.

The per-workspace half is :mod:`src.modules.finreports.tasks.harvest.workspace`;
this module decides who it is called for. That decision is the whole of the
hourly cost — the freshness gate, the gap survey, the reconciliation slice and
the single-flight lock are all here, and each of them exists because a tick that
walks everybody costs the fleet's WB budget.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import AsyncSessionLocal
from src.core.locks import single_flight
from src.core.logging import get_logger
from src.core.redis import get_redis
from src.core.timeutils import moscow_hour, moscow_today
from src.modules.finreports.constants import (
    HARVEST_LOCK_KEY,
    HARVEST_LOCK_TTL_SECONDS,
    RECONCILE_LOOKBACK_DAYS,
)
from src.modules.finreports.repos import (
    FinancialReportRepository,
    SettlementWatermarkRepository,
)
from src.modules.finreports.services.freshness_record import (
    FreshnessOutcome,
    FreshnessRecordStore,
)
from src.modules.finreports.services.publication import period_from
from src.modules.finreports.tasks.freshness import (
    check_freshness,
    freshness_record_store,
    settlement_blocked_for,
    verdict_from_walk,
)
from src.modules.finreports.tasks.gaps import survey_settlement_gaps
from src.modules.finreports.tasks.harvest.workspace import harvest_workspace
from src.modules.finreports.tasks.publication_spread import record_publication_spread
from src.modules.finreports.tasks.repair import gap_repair_due
from src.modules.finreports.tasks.spans import (
    reconciliation_slice,
    settlement_frontier,
    walk_span,
)
from src.modules.workspaces.contract import (
    WorkspaceTokenBundle,
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)

logger = get_logger(__name__)


#: Zeroed result shape, so a locked-out or empty run reports the same keys a
#: full one does and callers never have to guess whether a key is missing or 0.
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
}


async def harvest_all_workspaces(
    *, days: int, workspace_id: uuid.UUID | None = None, reconcile: bool = False
) -> dict[str, int]:
    """Harvest the last ``days`` for every workspace with a new WB report.

    Runs hourly, but only walks the sources for a workspace WB has published an
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
        days: How far back a workspace that has never been harvested reaches.
            One that has starts at its own last settled day — see
            :func:`_walk_span`, and :mod:`.settlement` for why the difference
            is now measured in quarter-hours rather than in requests.
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
            days=days, workspace_id=workspace_id, reconcile=reconcile
        )


async def _harvest_all_workspaces(
    *, days: int, workspace_id: uuid.UUID | None, reconcile: bool = False
) -> dict[str, int]:
    """Walk every eligible workspace. See :func:`harvest_all_workspaces`.

    The reconciliation pass exists because the ordinary one can only ever move
    forward. `_walk_span` starts at the watermark and the watermark jumps to the
    newest report's stated end, so the moment a weekly report lands, every
    earlier day leaves the reachable window for good. WB does not publish in
    that order — it forms single-day supplementary reports and starts serving
    their rows days later — and on 2026-08-31 that cost every workspace a day of
    settlement: report 983241109 was formed 09-01, was still unserved on 09-06
    (80 probes, every one of them a 204), and by the time WB served it the watermark had moved
    to 09-06 and nothing would ever ask again.
    """
    today = moscow_today()
    hour_msk = moscow_hour()
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
        # The periods we can prove we hold, which is what the gate now compares
        # WB's own period arithmetic against instead of sending a request. The
        # window is a little wider than the reconciliation's reach, so a report
        # WB serves weeks late is still recognised as the missing one rather
        # than as a period nobody remembers asking for.
        held_ends = {
            bundle.workspace_id: await report_repo.period_ends_since(
                workspace_id=bundle.workspace_id,
                since=today - timedelta(days=RECONCILE_LOOKBACK_DAYS + 7),
            )
            for bundle in bundles
        }
    # Surveyed on EVERY tick, not only the nightly one: the survey is SQL and
    # costs no WB request, so there is no reason to learn about a hole only when
    # its turn comes round. Rationing is about the walk, not about knowing.
    gaps = await survey_settlement_gaps(bundles, today=today, announce=reconcile)
    if reconcile:
        bundles = reconciliation_slice(bundles, today=today, gaps=gaps)
        repairing = {bundle.workspace_id for bundle in bundles}
    else:
        repairing = await gap_repair_due(bundles, today=today, gaps=gaps)
    totals = dict(_EMPTY_TOTALS)
    records: FreshnessRecordStore = freshness_record_store()
    for bundle in bundles:
        if not bundle.statistics:
            continue
        verdict = await check_freshness(
            tokens=bundle,
            latest_settled=settled[bundle.workspace_id],
            held_ends=held_ends[bundle.workspace_id],
            today=today,
            hour_msk=hour_msk,
            # «Обновить» and the nightly pass both arrive as `reconcile`, and
            # both must reach WB whatever the hour: a button that quietly did
            # nothing is worse than no button, and a safety net that only
            # catches at four preset hours is not much of one.
            paced=not reconcile,
            # Read from the shared Redis bucket, not from WB: asking WB whether
            # WB will accept a request is the one thing that cannot be done
            # here, and a peek takes no token.
            blocked_for=await settlement_blocked_for(bundle),
        )
        # `None` is a tick that asked nothing because the cadence paced it out
        # — see `is_probe_hour`. Nothing was learned, so nothing is recorded:
        # the standing verdict is still the most recent true one, and writing
        # over it would be claiming a check that did not happen. It must also
        # NOT be overridden by `thorough` below, for the same reason the probe
        # hours exist at all — a reconciliation pass that ignored the pace
        # would spend the whole budget on the days WB is late.
        if verdict is None:
            totals["workspaces_skipped"] += 1
            continue
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
        # lengthens the refusal. The router refuses a click for the same reason
        # before it ever enqueues; this is the same rule for the path that has
        # no router in front of it.
        if verdict.outcome is FreshnessOutcome.RATE_BLOCKED:
            totals["workspaces_skipped"] += 1
            continue
        if not verdict.should_harvest and not thorough:
            totals["workspaces_skipped"] += 1
            continue
        date_from, date_to = walk_span(
            latest_settled=settled[bundle.workspace_id],
            today=today,
            days=days,
            lookback_days=RECONCILE_LOOKBACK_DAYS if thorough else 0,
        )
        # The span is aligned to what the gate asked about, and on the ordinary
        # path it is set to exactly that.
        #
        # Two things are going on. The first is correctness: the span MUST
        # reach the gate's window, or the walk is sent out for a report it
        # structurally cannot fetch — the 31.08 failure restated one layer
        # down, since `walk_span` starts at the watermark and the watermark had
        # jumped past 31.08 the moment the 01.09-06.09 report landed.
        #
        # The second is cost, and it is why the ordinary path ASSIGNS rather
        # than taking a minimum. `walk_span` starts AT the last settled day, so
        # its span runs 13.09..20.09 — eight days, which `settlement_windows`
        # cuts into two weekly windows and therefore two quarter-hourly
        # requests, one of them re-reading a week already on file. Starting at
        # the missing period's own first day makes it 14.09..20.09: one window,
        # one request. Half the walk, per seller, per cycle.
        #
        # What that re-read was buying is WB's amendments to a week we already
        # hold, and it is not thrown away — it moves to the thorough path,
        # which keeps the `min` and reaches RECONCILE_LOOKBACK_DAYS behind the
        # watermark. So an amendment is picked up by the nightly pass or by
        # «Обновить» within a day, instead of within an hour, and that is the
        # whole price.
        if verdict.probe_from is not None and verdict.probe_to is not None:
            date_from = min(date_from, verdict.probe_from) if thorough else verdict.probe_from
            # And it stops where the gate stopped. `walk_span` ends at
            # yesterday, which on any day but a Monday reaches into the period
            # WB has not closed yet — an extra weekly window, an extra
            # quarter-hourly request, and 204 the only answer it can get.
            date_to = max(verdict.probe_to, date_to) if thorough else verdict.probe_to
        counts = await harvest_workspace(
            tokens=bundle, date_from=date_from, date_to=date_to, on_date=today
        )
        for key, value in counts.items():
            totals[key] += value
        if counts.get("finance") and verdict.probe_from is not None:
            # The measurement shared discovery is waiting on: did WB serve this
            # period to everyone at once? Every seller is asking that question
            # for itself, once an hour, on the day the report lands — one
            # answer could serve the fleet, and at fifty sellers that is the
            # difference between a ceiling of eighteen per egress address and
            # sixty. Nothing we hold says whether WB publishes simultaneously,
            # so this records it before anything is built on it.
            async with AsyncSessionLocal() as session:
                await record_publication_spread(
                    session,
                    workspace_id=bundle.workspace_id,
                    period_end=period_from(verdict.probe_from).date_to,
                    name=bundle.name,
                )
        # And recorded AGAIN, from what the walk found. The walk asks WB about
        # the same days the probe did, so a completed one is strictly better
        # evidence — and throwing it away is the same discard bug one level up.
        #
        # It is not hypothetical. On 2026-09-09 the probe hit the settlement
        # endpoint's 15-minute block and 429'd, the gate failed open, and seven
        # minutes later the walk asked the same window and got 204 — proof there
        # was nothing new. The page kept showing «не удалось спросить — данные
        # могут быть неполными» over a statement that had just been confirmed
        # complete. The reverse goes stale too: a verdict of «опубликован новый
        # отчёт — загружаем» outlives the load that fetched it.
        if not counts.get("finance_windows_failed"):
            await records.put(
                bundle.workspace_id,
                await verdict_from_walk(
                    workspace_id=bundle.workspace_id,
                    settled_before=settled[bundle.workspace_id],
                    date_from=date_from,
                    date_to=date_to,
                ),
            )
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
