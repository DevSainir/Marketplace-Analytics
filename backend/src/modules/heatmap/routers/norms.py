"""HTTP routes for the heatmap's hand-set norms — a lab feature.

``require_internal`` on this router, on top of the heatmap's own module grants:
the heatmap itself is open to every subscriber, «Норма: ручной ввод» is still
being tried out at /labs/heatmap and only we may reach it. The SPA hides it
from everyone else; this refuses it to them.

Reads take the tenant from ``X-Workspace-Id``. Writes take ``WritingAccess`` as
well: a norm is shared by everyone in the кабинет and changes how their grid is
painted, so a read-only manager must not be able to set or clear one. The
module grants on the router are not enough for that — they say which sections
the caller may open, not whether they may change anything in them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from src.core.deps import DbSession
from src.modules.heatmap.deps import SkuNormServiceDep
from src.modules.heatmap.schemas import MetricKey, SkuNormList, SkuNormRead, SkuNormWrite
from src.modules.organizations.contract import WritingAccess, require_internal
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter(prefix="/heatmap/norms", dependencies=[Depends(require_internal)])

NmId = Annotated[int, Path(ge=1)]


@router.get(
    "",
    response_model=SkuNormList,
    status_code=status.HTTP_200_OK,
    responses={401: {"description": "Unauthorized access token."}},
)
async def list_norms(service: SkuNormServiceDep, workspace_id: CurrentWorkspaceId) -> SkuNormList:
    """Return every norm the кабинет has set — bounded by its cards times the metrics."""
    return await service.list_norms(workspace_id=workspace_id)


@router.put(
    "/{nm_id}/{metric}",
    response_model=SkuNormRead,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Unauthorized access token."},
        403: {"description": "Доступ только для чтения."},
        422: {"description": "Артикула нет в каталоге кабинета или значение вне границ."},
    },
)
async def set_norm(
    _writer: WritingAccess,
    nm_id: NmId,
    metric: MetricKey,
    payload: SkuNormWrite,
    service: SkuNormServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
) -> SkuNormRead:
    """Set an article's norm on one metric, per day."""
    return await service.set_norm(
        session, workspace_id=workspace_id, nm_id=nm_id, metric=metric, value=payload.value
    )


@router.delete(
    "/{nm_id}/{metric}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Unauthorized access token."},
        403: {"description": "Доступ только для чтения."},
    },
)
async def clear_norm(
    _writer: WritingAccess,
    nm_id: NmId,
    metric: MetricKey,
    service: SkuNormServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> None:
    """Clear an article's norm; the article goes back to the default one."""
    await service.clear_norm(workspace_id=workspace_id, nm_id=nm_id, metric=metric)
