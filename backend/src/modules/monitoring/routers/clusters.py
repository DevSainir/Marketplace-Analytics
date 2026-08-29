"""«Поиск по кластерам» — the SKU's advertising clusters.

One route: the per-cluster history, two indexed aggregates that load with the
SKU. It takes its ``nm_id`` through the :data:`WorkspaceSku` guard, so another
workspace's SKU is indistinguishable from a nonexistent one.

The live position probe and the pinned phrases that used to live here were
removed on 2026-08-27 — see ``docs/monitoring/LIVE_POSITION.md``.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, status

from src.modules.monitoring.deps import ClusterAnalyticsDep, WorkspaceSku
from src.modules.monitoring.schemas.clusters import SkuClustersResponse

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
