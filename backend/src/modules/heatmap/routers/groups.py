"""HTTP routes for the heatmap's «Группы».

Reads take the tenant from ``X-Workspace-Id``. Writes take ``WritingAccess`` as
well: a group is shared by everyone in the кабинет and changes what their
filter lists, so a read-only manager — or a guest reading another company's
кабинет — must not be able to make or remove one. The module grants on the
router are not enough on their own for that: they say which sections the
caller may open, not whether they may change anything in them.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import DbSession
from src.modules.heatmap.deps import SkuGroupServiceDep
from src.modules.heatmap.schemas import SkuGroupList, SkuGroupRead, SkuGroupWrite
from src.modules.organizations.contract import WritingAccess
from src.modules.workspaces.contract import CurrentWorkspaceId

router = APIRouter(prefix="/heatmap/groups")

_WRITE_ERRORS: dict[int | str, dict[str, str]] = {
    401: {"description": "Unauthorized access token."},
    403: {"description": "Доступ только для чтения."},
    409: {"description": "Группа с таким названием уже есть."},
    422: {"description": "Название пустое, артикулов нет в каталоге или достигнут лимит."},
}


@router.get(
    "",
    response_model=SkuGroupList,
    status_code=status.HTTP_200_OK,
    responses={401: {"description": "Unauthorized access token."}},
)
async def list_groups(
    service: SkuGroupServiceDep, workspace_id: CurrentWorkspaceId
) -> SkuGroupList:
    """Return every group of the кабинет, by name."""
    return await service.list_groups(workspace_id=workspace_id)


@router.post(
    "",
    response_model=SkuGroupRead,
    status_code=status.HTTP_201_CREATED,
    responses=_WRITE_ERRORS,
)
async def create_group(
    _writer: WritingAccess,
    payload: SkuGroupWrite,
    service: SkuGroupServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
) -> SkuGroupRead:
    """Create a group of the кабинет's articles."""
    return await service.create(session, workspace_id=workspace_id, payload=payload)


@router.put(
    "/{group_id}",
    response_model=SkuGroupRead,
    status_code=status.HTTP_200_OK,
    responses={**_WRITE_ERRORS, 404: {"description": "Группа не найдена."}},
)
async def update_group(
    _writer: WritingAccess,
    group_id: uuid.UUID,
    payload: SkuGroupWrite,
    service: SkuGroupServiceDep,
    workspace_id: CurrentWorkspaceId,
    session: DbSession,
) -> SkuGroupRead:
    """Replace a group's name and members.

    A group of another кабинет is reported as missing, not forbidden — a guessed
    id must not confirm that the group exists.
    """
    return await service.update(
        session, workspace_id=workspace_id, group_id=group_id, payload=payload
    )


@router.delete(
    "/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Unauthorized access token."},
        403: {"description": "Доступ только для чтения."},
        404: {"description": "Группа не найдена."},
    },
)
async def delete_group(
    _writer: WritingAccess,
    group_id: uuid.UUID,
    service: SkuGroupServiceDep,
    workspace_id: CurrentWorkspaceId,
) -> None:
    """Delete a group; its articles are untouched."""
    await service.delete(workspace_id=workspace_id, group_id=group_id)
