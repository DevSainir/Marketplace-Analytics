"""The manual «Обновить» surface: fetch WB's finance reports now.

Two routes on one path — ``POST /harvest`` asks for a harvest, ``GET /harvest``
reports whether one is running and how far the history reaches, so the frontend
can poll and then reload the statement.

The schedule asks WB on the hours a report can arrive, and only while a seller
is still owed one; this exists for the moments it cannot cover. A report served
off the calendar waits for the 04:00 pass, and a worker that was down for its
tick waits for the next one — in both cases the seller can already see the report on WB's own
site, and «подождите» is not an answer.

Triggering is guarded, not queued: if a harvest is already in flight the answer
is ``already_running`` and nothing is enqueued. The guard is advisory (see
:class:`~src.modules.finreports.services.harvest_control.HarvestControlService`)
and it is not what makes overlapping runs safe — the task takes the same lock
before it walks anything, so even a request that slips through the race finds
the lock held and returns without touching WB.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, status

from src.modules.finreports.deps import HarvestControlServiceDep
from src.modules.finreports.schemas import (
    AwaitedReportOut,
    FreshnessCheckOut,
    HarvestStateResponse,
    HarvestTriggerResponse,
    LatestReportOut,
)
from src.modules.finreports.tasks import harvest_daily_tail, harvest_finance
from src.modules.organizations.contract import WritingAccess
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter()


@router.get(
    "/harvest",
    response_model=HarvestStateResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Whether a harvest is running and what it has covered."},
        401: {"description": "Unauthorized access token."},
    },
)
async def get_harvest_state(
    service: HarvestControlServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> HarvestStateResponse:
    """Report harvest liveness, settlement coverage and freshness.

    Polled by «Обновить» while a run is in flight: ``running`` falling to false
    is the signal to re-fetch the statement, and ``latest_settled`` moving is
    what tells the seller a new week actually arrived. It is also read on every
    load of the P&L, which renders ``latest_report`` and ``last_check`` as the
    line saying why the statement stops where it does.

    Read-only despite spending nothing: **this route never asks WB anything.**
    It relays what the hourly task recorded. A page load may not spend the WB
    request budget the schedule is metered against, and the freshness answer is
    only meaningful *because* it says when somebody else last asked.

    Guard: the module's router-level ``MemberAccess`` — the paywall every
    finreports data route sits behind. Nothing weaker would do: the answer names
    a tenant's settlement weeks and harvest timings. Scoped by
    ``CurrentWorkspaceId``, which validates the header against the caller's own
    organisation and binds the tenant for row-level security.
    """
    state = await service.get_state(workspace_id=workspace_id)
    report = state.latest_report
    check = state.last_check
    return HarvestStateResponse(
        running=state.running,
        latest_settled=state.latest_settled,
        provisional_through=state.provisional_through,
        awaited_report=(
            AwaitedReportOut(date_from=state.awaited_period[0], date_to=state.awaited_period[1])
            if state.awaited_period is not None
            else None
        ),
        latest_report=(
            LatestReportOut(
                report_id=report.report_id,
                date_from=report.date_from,
                date_to=report.date_to,
                harvested_at=report.harvested_at,
            )
            if report is not None
            else None
        ),
        last_check=(
            FreshnessCheckOut(
                outcome=check.outcome.value,
                checked_at=check.checked_at,
                probe_from=check.probe_from,
                probe_to=check.probe_to,
            )
            if check is not None
            else None
        ),
    )


@router.post(
    "/harvest",
    response_model=HarvestTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "A harvest was enqueued, or one was already running."},
        401: {"description": "Unauthorized access token."},
    },
)
async def trigger_harvest(
    _writer: WritingAccess,
    service: HarvestControlServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> HarvestTriggerResponse:
    """Ask WB now for any finance report we do not already hold.

    **The gate does not apply to a person.** This used to enqueue the ordinary
    gated tick, so a click answered whatever the hourly schedule had already
    answered — and the one moment somebody presses «Обновить» is the moment the
    schedule has just told them the statement is complete when it is not. On
    2026-09-14 the click was logged as «settled through 13.09 — nothing newer can
    exist yet, skipping» over a week WB had published that morning.

    So the click walks the reconciliation span: the days behind our coverage as
    well as the ones after it, whatever the gate says. That is the only shape
    that answers the question actually being asked, which is not «есть ли что-то
    новее» but «догони то, что у WB уже есть, а у нас нет». It costs more — a
    fortnight was three windows of the old endpoint's quarter-hourly budget, and
    is a few one-a-minute requests on finance-api — and it is spent on
    the caller's own workspace, once, because a person asked.

    The earlier reasoning for the gated version, kept because it was not wrong
    about the cost: widening a click into a fortnight of re-reads spends a
    seller's settlement budget on data already on file, and the daily pass covers
    it anyway. What it got wrong is «anyway» — the daily pass takes one workspace
    a night, so «anyway» is up to five days, and this button exists precisely for
    the case where waiting is not the answer.

    **Every outcome is an answer, and none of them is a wait.** WB metered the
    old settlement report at one request per ~15 minutes, so a click shortly
    after the hourly tick used to enqueue a harvest whose first act was to sit still
    for most of that window — seven minutes of «Обновляем…» during which nothing
    could possibly happen (prod 2026-09-09). The bucket already knows, in shared
    Redis, so that case is now refused here with the wait attached instead of
    being discovered minutes later on a worker.

    "Already running" and "rate limited" are reported as normal outcomes (202)
    rather than conflicts, because they are: in the first the data the caller
    wants is already being fetched, and in the second there is nothing anyone
    could do differently until the bucket reopens.

    Order matters — a run in flight is reported ahead of the rate limit. The
    running harvest is very often what emptied the bucket, and "уже идёт" is the
    more useful half of that pair: it says the work is happening, where the rate
    limit alone would say only that it cannot start.

    Scoped to the caller's own workspace. It used to enqueue the **fleet** walk:
    one seller pressing «Обновить» spent every other seller's WB rate budget and
    held the shared harvest lock for the length of a platform-wide walk, so the
    cost of one click grew with the number of tenants and landed on all of them.
    """
    state = await service.get_state(workspace_id=workspace_id)
    if state.running:
        return HarvestTriggerResponse(status="already_running")
    retry_after = await service.settlement_retry_after(workspace_id=workspace_id)
    if retry_after > 0:
        return HarvestTriggerResponse(
            status="rate_limited", retry_after_seconds=math.ceil(retry_after)
        )
    task = harvest_finance.delay(workspace_id=str(workspace_id), reconcile=True)
    # And the provisional tail, as a second task rather than a step inside the
    # first. The settled walk can sit for minutes waiting for WB's next token,
    # and the days this fetches — the ones between the last weekly report and
    # yesterday — are usually the ones the seller is looking at when they press
    # the button. Behind the walk they would arrive last; beside it they arrive
    # while it is still pacing. Both are scoped to the caller's own workspace.
    #
    # Its result is not reported back: the button polls `GET /harvest`, which
    # already answers «what do we hold now», and a second task id would only
    # invite the frontend to wait on a run whose rows it can already see.
    harvest_daily_tail.delay(workspace_id=str(workspace_id))
    return HarvestTriggerResponse(status="started", task_id=task.id)
