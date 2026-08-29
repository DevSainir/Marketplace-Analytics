"""The manual «Обновить» surface: fetch WB's finance reports now.

Two routes on one path — ``POST /harvest`` asks for a harvest, ``GET /harvest``
reports whether one is running and how far the history reaches, so the frontend
can poll and then reload the statement.

The schedule already asks WB hourly; this exists for the hours it cannot cover.
A report published overnight waits for the 08:00 tick, and a worker that was
down for its tick waits for the next one — in both cases the seller can already
see the report on WB's own site, and «подождите до утра» is not an answer.

Triggering is guarded, not queued: if a harvest is already in flight the answer
is ``already_running`` and nothing is enqueued. The guard is advisory (see
:class:`~src.modules.finreports.services.harvest_control.HarvestControlService`)
and it is not what makes overlapping runs safe — the task takes the same lock
before it walks anything, so even a request that slips through the race finds
the lock held and returns without touching WB.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from src.modules.finreports.deps import HarvestControlServiceDep
from src.modules.finreports.schemas import HarvestStateResponse, HarvestTriggerResponse
from src.modules.finreports.tasks import harvest_finance
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
    """Report harvest liveness and this workspace's settlement coverage.

    Polled by «Обновить» while a run is in flight: ``running`` falling to false
    is the signal to re-fetch the statement, and ``latest_settled`` moving is
    what tells the seller a new week actually arrived.
    """
    state = await service.get_state(workspace_id=workspace_id)
    return HarvestStateResponse(running=state.running, latest_settled=state.latest_settled)


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

    Enqueues the same task the schedule runs, so the freshness gate still
    applies: a workspace WB has published nothing new for is skipped after one
    request rather than walked.

    "Already running" is reported as a normal outcome (202) rather than a
    conflict, because it is one: the data the caller wants is being fetched, and
    the only thing that did not happen is a second, redundant run.

    Scoped to the caller's own workspace. It used to enqueue the **fleet** walk:
    one seller pressing «Обновить» spent every other seller's WB rate budget and
    held the shared harvest lock for the length of a platform-wide walk, so the
    cost of one click grew with the number of tenants and landed on all of them.
    """
    state = await service.get_state(workspace_id=workspace_id)
    if state.running:
        return HarvestTriggerResponse(status="already_running")
    task = harvest_finance.delay(workspace_id=str(workspace_id))
    return HarvestTriggerResponse(status="started", task_id=task.id)
