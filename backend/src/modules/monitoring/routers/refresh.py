"""The WB re-harvest trigger surface: enqueue a refresh, then poll it.

The two enqueueing routes carry ``WritingAccess`` rather than plain membership:
a refresh is not a read. It spends the WB rate budget the whole platform shares,
and a tenant past its grace window must not be able to spend it.

Split from the read/query routes because it answers a different question of the
same module — "go fetch fresh WB data", not "show me what we have". Three routes:
one SKU (:func:`refresh_sku`), the whole catalogue (:func:`refresh_all_skus`),
and the shared status poll (:func:`get_refresh_status`). The parent router adds
the ``/v1/monitoring`` prefix and the access-token dependency.
"""

from __future__ import annotations

from celery.result import AsyncResult
from fastapi import APIRouter, status

from src.core.celery_app import celery_app
from src.core.exceptions import NotFoundError
from src.modules.monitoring.deps import (
    AnalyticsServiceDep,
    CurrentWorkspaceId,
    WorkspaceSku,
)
from src.modules.monitoring.schemas import (
    RefreshEnqueuedResponse,
    RefreshStatusResponse,
)
from src.modules.monitoring.services import (
    bind_task_to_workspace,
    remember_running_task,
    spend_refresh_budget,
    task_already_running,
    task_belongs_to_workspace,
)
from src.modules.monitoring.tasks import discover_workspace, harvest_sku_window
from src.modules.organizations.contract import WritingAccess

router = APIRouter()


@router.post(
    "/skus/{nm_id}/refresh",
    response_model=RefreshEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "A WB refresh for this SKU was enqueued."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "SKU not found in this workspace."},
        429: {"description": "This workspace's refresh budget is spent."},
    },
)
async def refresh_sku(
    _writer: WritingAccess,
    nm_id: WorkspaceSku,
    workspace_id: CurrentWorkspaceId,
) -> RefreshEnqueuedResponse:
    """Enqueue a fresh WB harvest for one SKU (discards its manual edits).

    Runs the harvest over WB's serviceable recent window (the funnel-history
    endpoint caps at 7 days); older days keep their last-harvested values. The
    harvest ingests fresh facts and clears this SKU's overrides. Poll
    ``GET /refresh/{task_id}`` for completion, then re-fetch the detail.

    The task id is bound to the caller's workspace so only that workspace can
    read its status back.

    Bounded two ways. A second press while the first harvest is still in flight
    gets that task's id back rather than a second run; beyond that, the
    workspace's enqueue budget applies, because the Celery pool and the WB rate
    budget it spends are shared with every other tenant and with the scheduled
    harvests.
    """
    running = await task_already_running(workspace_id, [nm_id])
    if running is not None:
        return RefreshEnqueuedResponse(task_id=running)
    await spend_refresh_budget(workspace_id)
    task = harvest_sku_window.delay([nm_id])
    await bind_task_to_workspace(task.id, workspace_id)
    await remember_running_task(workspace_id, [nm_id], task.id)
    return RefreshEnqueuedResponse(task_id=task.id)


@router.post(
    "/skus/refresh-all",
    response_model=RefreshEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {
            "description": "A WB refresh, or a SKU discovery when the catalogue is empty.",
        },
        401: {"description": "Unauthorized access token."},
        429: {"description": "This workspace's refresh budget is spent."},
    },
)
async def refresh_all_skus(
    _writer: WritingAccess,
    service: AnalyticsServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> RefreshEnqueuedResponse:
    """Enqueue a fresh WB harvest for **every** SKU in the workspace.

    The bulk counterpart of :func:`refresh_sku`: one task harvests the whole
    catalogue (discarding those SKUs' manual edits), so it is heavier and slower
    than a single-SKU refresh. Both now refresh the same FAMILIES of data —
    funnel, stocks, advertising, prices, the account-wide sale feed and the
    buyout cohorts — and differ only in how many SKUs the per-SKU sources cover.

    A workspace with an empty catalogue gets ``monitoring.discover_workspace``
    instead: it reads the SKU list from the Content API with the workspace's own
    token and harvests what comes back. Both answer 202 with a task id, so the
    SPA polls one route either way and needs no knowledge of which ran.

    Poll ``GET /refresh/{task_id}`` for completion exactly as for one SKU. The
    task id is bound to the caller's workspace so only that workspace can read
    its status back.
    """
    nm_ids = await service.list_workspace_nm_ids(workspace_id=workspace_id)
    if not nm_ids:
        # An empty catalogue is a workspace whose WB token was set recently, not
        # a mistake: nothing but the Content API can say which SKUs exist, and
        # the only pass that read it was the nightly one. So this answered 404
        # — «нет ни одного артикула» — until 06:00 MSK, with no button anywhere
        # that could fix it. Discovery is what "refresh everything" MEANS here.
        # The same budget and in-flight guard apply; an empty SKU set is a
        # stable, distinct dedup key, so a second press rejoins the first run.
        running = await task_already_running(workspace_id, [])
        if running is not None:
            return RefreshEnqueuedResponse(task_id=running)
        await spend_refresh_budget(workspace_id)
        task = discover_workspace.delay(workspace_id=str(workspace_id))
        await bind_task_to_workspace(task.id, workspace_id)
        await remember_running_task(workspace_id, [], task.id)
        return RefreshEnqueuedResponse(task_id=task.id)
    running = await task_already_running(workspace_id, nm_ids)
    if running is not None:
        return RefreshEnqueuedResponse(task_id=running)
    await spend_refresh_budget(workspace_id)
    task = harvest_sku_window.delay(nm_ids)
    await bind_task_to_workspace(task.id, workspace_id)
    await remember_running_task(workspace_id, nm_ids, task.id)
    return RefreshEnqueuedResponse(task_id=task.id)


def _failed_sources(result: AsyncResult[object]) -> list[str]:
    """Read the ``failed_sources`` list out of a finished harvest's return value.

    Defensive about the shape: the value comes back through the Celery result
    backend, and an older task payload (enqueued before this field existed, or
    by a previous deploy mid-rollout) simply has no such key.

    Args:
        result: A successful task's ``AsyncResult``.

    Returns:
        The WB source labels that did not answer, or an empty list.
    """
    payload = result.result
    if not isinstance(payload, dict):
        return []
    sources = payload.get("failed_sources")
    if not isinstance(sources, list):
        return []
    return [str(source) for source in sources]


@router.get(
    "/refresh/{task_id}",
    response_model=RefreshStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Current state of a single-SKU refresh task."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such refresh task in this workspace."},
    },
)
async def get_refresh_status(
    task_id: str,
    workspace_id: CurrentWorkspaceId,
) -> RefreshStatusResponse:
    """Report a refresh task's state so the frontend knows when to re-fetch.

    Scoped to the workspace that enqueued the task: Celery's ``AsyncResult``
    would happily report on any id in the broker, which let one workspace learn
    whether another's harvest had run and whether it succeeded. An id belonging
    to another tenant is indistinguishable from one that never existed.
    """
    if not await task_belongs_to_workspace(task_id, workspace_id):
        raise NotFoundError(f"Задача обновления {task_id} не найдена.")
    result: AsyncResult[object] = AsyncResult(task_id, app=celery_app)
    ready = result.ready()
    successful = bool(result.successful()) if ready else False
    return RefreshStatusResponse(
        task_id=task_id,
        status=str(result.state),
        ready=ready,
        successful=successful,
        failed_sources=_failed_sources(result) if successful else [],
    )
