"""«Поиск по кластерам» endpoints — all scoped to one SKU.

Routes for one page section whose parts cost very different things: the cluster
history is two indexed aggregates and loads with the SKU; the pinned phrases are
one small table and load with it too; the position probe walks WB's public search
under a per-IP rate limit and only runs when someone asks. Splitting them keeps a
throttled WB from delaying — or failing — the parts that are always shown.

The pins are a standing version of the probe: «Закрепить» stores the phrase, and
the scheduled task (three runs a day) writes each one's latest position back onto
it, so the cards carry a number without anyone pressing anything.

Every route takes its ``nm_id`` through the :data:`WorkspaceSku` guard, so
another workspace's SKU is indistinguishable from a nonexistent one.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, status

from src.modules.monitoring.deps import (
    ClusterAnalyticsDep,
    CurrentWorkspaceId,
    PinnedKeywordServiceDep,
    WorkspaceSku,
)
from src.modules.monitoring.schemas.clusters import (
    PinKeywordRequest,
    PinnedKeywordItem,
    PinnedKeywordsResponse,
    PositionRefreshAccepted,
    SkuClustersResponse,
    SkuSearchPositionResponse,
)
from src.modules.monitoring.services import bind_task_to_workspace
from src.modules.monitoring.tasks import refresh_pinned_positions

router = APIRouter(tags=["Monitoring"])


@router.get(
    "/skus/{nm_id}/clusters",
    response_model=SkuClustersResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The SKU's search clusters over the window, best first."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such SKU in the active workspace."},
        422: {"description": "Invalid date window."},
    },
)
async def get_sku_clusters(
    nm_id: WorkspaceSku,
    service: ClusterAnalyticsDep,
    date_from: date | None = Query(default=None, description="Inclusive start."),
    date_to: date | None = Query(default=None, description="Inclusive end."),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum clusters returned."),
) -> SkuClustersResponse:
    """Return the search clusters this SKU's advertising served in."""
    return await service.clusters_for_sku(
        nm_id=nm_id, date_from=date_from, date_to=date_to, limit=limit
    )


@router.get(
    "/skus/{nm_id}/search-position",
    response_model=SkuSearchPositionResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The SKU's live rank for the phrase (or None if unfound)."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such SKU in the active workspace."},
        422: {"description": "Blank or over-long phrase."},
        502: {"description": "WB's public search did not answer (throttled or changed)."},
    },
)
async def probe_sku_position(
    nm_id: WorkspaceSku,
    service: ClusterAnalyticsDep,
    workspace_id: CurrentWorkspaceId,
    query: str = Query(min_length=1, description="The phrase a shopper would type."),
    refresh: bool = Query(
        default=False,
        description="Skip the cached scan and re-check WB now (costs rate budget).",
    ),
) -> SkuSearchPositionResponse:
    """Report where this SKU currently ranks in WB search for a phrase.

    Live, not history: a sample for the configured delivery region and loyalty
    tier, cached briefly and shared across the workspace's SKUs.
    """
    return await service.probe_position(
        nm_id=nm_id, workspace_id=workspace_id, query=query, refresh=refresh
    )


@router.get(
    "/skus/{nm_id}/pinned-keywords",
    response_model=PinnedKeywordsResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The SKU's pinned phrases with their last known positions."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such SKU in the active workspace."},
    },
)
async def list_pinned_keywords(
    nm_id: WorkspaceSku,
    service: PinnedKeywordServiceDep,
) -> PinnedKeywordsResponse:
    """List the phrases pinned to this SKU and each one's latest position.

    Stored, not live: every number here was written by a scheduled run and
    carries the timestamp it was taken at. Nothing in this route talks to WB, so
    it answers while the probe is throttled.
    """
    return await service.list_for_sku(nm_id=nm_id)


@router.post(
    "/skus/{nm_id}/pinned-keywords",
    response_model=PinnedKeywordItem,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "The phrase is pinned (idempotent — re-pinning keeps its number)."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such SKU in the active workspace."},
        422: {"description": "Blank or over-long phrase."},
    },
)
async def pin_keyword(
    nm_id: WorkspaceSku,
    payload: PinKeywordRequest,
    service: PinnedKeywordServiceDep,
) -> PinnedKeywordItem:
    """Pin a phrase to this SKU so its position is re-checked on the schedule.

    The card comes back without a position: pinning does not probe (that would
    put a rate-limited WB call behind a button meant to feel instant). The next
    scheduled run, or «Проверить все позиции», fills it in.
    """
    return await service.pin(nm_id=nm_id, keyword=payload.keyword)


@router.delete(
    "/skus/{nm_id}/pinned-keywords/{keyword}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "The phrase is no longer pinned."},
        401: {"description": "Unauthorized access token."},
        404: {"description": "No such SKU, or that phrase was not pinned to it."},
    },
)
async def unpin_keyword(
    nm_id: WorkspaceSku,
    keyword: str,
    service: PinnedKeywordServiceDep,
) -> None:
    """Unpin a phrase from this SKU."""
    await service.unpin(nm_id=nm_id, keyword=keyword)


@router.post(
    "/positions/refresh",
    response_model=PositionRefreshAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {"description": "A refresh of every pinned phrase was enqueued."},
        401: {"description": "Unauthorized access token."},
    },
)
async def refresh_all_positions(
    service: PinnedKeywordServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> PositionRefreshAccepted:
    """«Проверить все позиции» — re-probe every phrase this workspace pinned.

    The same task the schedule runs three times a day, scoped to the caller's
    workspace. Enqueued rather than awaited: phrases are probed about a minute
    apart (WB refuses back-to-back requests), so a catalogue of pins takes longer
    than any HTTP request should live. Poll ``GET /refresh/{task_id}``.

    Returns the pin count so the UI can distinguish "queued 12 phrases" from the
    silent no-op of a workspace that has pinned nothing.
    """
    pinned = await service.count_for_workspace(workspace_id=workspace_id)
    task = refresh_pinned_positions.delay(str(workspace_id))
    await bind_task_to_workspace(task.id, workspace_id)
    return PositionRefreshAccepted(task_id=task.id, pinned_count=pinned)
