"""HTTP presentation layer for the Workspaces module.

Listing is open to any authenticated user (workspace membership/roles arrive
later); creation, deletion, and token management require the ``dev`` role.
Domain errors (``ConflictError``, ``NotFoundError``, ``PermissionDeniedError``)
propagate to the global ``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from src.modules.users.contract import CurrentUserId, require_dev_role
from src.modules.workspaces.deps import WorkspaceServiceDep
from src.modules.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceRead,
    WorkspaceTokensStatus,
    WorkspaceTokensUpdateRequest,
)

router = APIRouter(prefix="/v1/workspaces", tags=["Workspaces"])

#: Route-level guard for workspace administration (dev role only).
_dev_only = Depends(require_dev_role)


@router.get(
    "",
    response_model=WorkspaceListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Every workspace (open to any authenticated user)."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def list_workspaces(
    _user_id: CurrentUserId,
    service: WorkspaceServiceDep,
) -> WorkspaceListResponse:
    """List every workspace the caller can switch into (all, for now)."""
    return WorkspaceListResponse(items=await service.list_workspaces())


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_dev_only],
    responses={
        201: {"description": "Workspace created."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Developer role required."},
        409: {"description": "Workspace name already exists."},
    },
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    """Create a new workspace (dev only)."""
    return await service.create_workspace(name=payload.name)


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_dev_only],
    responses={
        204: {"description": "Workspace and its stored tokens deleted."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Developer role required."},
        404: {"description": "Workspace not found."},
    },
)
async def delete_workspace(
    workspace_id: uuid.UUID,
    service: WorkspaceServiceDep,
) -> None:
    """Delete a workspace and its WB tokens (dev only)."""
    await service.delete_workspace(workspace_id)


@router.get(
    "/{workspace_id}/tokens",
    response_model=WorkspaceTokensStatus,
    status_code=status.HTTP_200_OK,
    dependencies=[_dev_only],
    responses={
        200: {"description": "Which WB surfaces have a token configured."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Developer role required."},
        404: {"description": "Workspace not found."},
    },
)
async def get_token_status(
    workspace_id: uuid.UUID,
    service: WorkspaceServiceDep,
) -> WorkspaceTokensStatus:
    """Report the workspace's per-surface token configuration (dev only).

    Token *values* are never returned — only booleans per WB surface.
    """
    return await service.token_status(workspace_id)


@router.put(
    "/{workspace_id}/tokens",
    response_model=WorkspaceTokensStatus,
    status_code=status.HTTP_200_OK,
    dependencies=[_dev_only],
    responses={
        200: {"description": "Tokens updated; resulting configuration status."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Developer role required."},
        404: {"description": "Workspace not found."},
        422: {"description": "Token kind not valid for this workspace's mode."},
    },
)
async def set_tokens(
    workspace_id: uuid.UUID,
    payload: WorkspaceTokensUpdateRequest,
    service: WorkspaceServiceDep,
) -> WorkspaceTokensStatus:
    """Set/rotate the workspace's WB tokens (dev only).

    Partial update: omitted surfaces are untouched; an empty string deletes
    the stored token for that surface. Values are Fernet-encrypted at rest.
    """
    return await service.set_tokens(workspace_id, payload)
