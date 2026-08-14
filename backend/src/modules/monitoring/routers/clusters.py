"""«Поиск по кластерам» endpoints — both scoped to one SKU.

Two routes for one page section, because the two halves cost very different
things: the cluster history is two indexed aggregates and loads with the SKU,
while the position probe walks WB's public search under a per-IP rate limit and
only runs when someone types a phrase. Splitting them keeps a throttled WB from
delaying — or failing — the part that is always shown.

Both take their ``nm_id`` through the :data:`WorkspaceSku` guard, so another
workspace's SKU is indistinguishable from a nonexistent one.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, status

from src.modules.monitoring.deps import ClusterAnalyticsDep, CurrentWorkspaceId, WorkspaceSku
from src.modules.monitoring.schemas.clusters import (
    SkuClustersResponse,
    SkuSearchPositionResponse,
)

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
