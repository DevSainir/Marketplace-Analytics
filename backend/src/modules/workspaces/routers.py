"""HTTP presentation layer for the Workspaces module.

Every route here is scoped to the caller's own organisation, and the guards say
who may do what:

* **listing** needs only membership — a manager has to be able to switch between
  the workspaces they work in;
* **creating, deleting and managing WB tokens** need ``owner``. These change
  what the company IS and what it costs, and a WB token is the credential to a
  seller's live account.

Until 2026-08-27 the write routes were gated on the ``dev`` role and the list
returned every workspace on the platform. Both are now tenant-scoped: a
workspace belonging to another organisation reads as 404, never 403, so these
endpoints cannot be used to discover other sellers' workspace ids.

Domain errors propagate to the global ``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from src.core.deps import DbSession
from src.modules.organizations.contract import (
    AuditEvent,
    AuditTrail,
    MemberAccess,
    OwnerAccess,
    load_workspace_quota,
    require_owner,
)
from src.modules.workspaces.deps import PathWorkspaceId, WorkspaceServiceDep
from src.modules.workspaces.schemas import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceRead,
    WorkspaceTokensStatus,
    WorkspaceTokensUpdateRequest,
)

router = APIRouter(prefix="/v1/workspaces", tags=["Workspaces"])

#: Route-level guard for workspace administration.
_owner_only = Depends(require_owner)


@router.get(
    "",
    response_model=WorkspaceListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The caller's organisation's workspaces."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "The account belongs to no organisation."},
    },
)
async def list_workspaces(
    access: MemberAccess,
    service: WorkspaceServiceDep,
) -> WorkspaceListResponse:
    """List the workspaces the caller may switch between."""
    return WorkspaceListResponse(
        items=await service.list_workspaces(organization_id=access.tenant_id)
    )


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_owner_only],
    responses={
        201: {"description": "Workspace created inside the caller's organisation."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Owner role required."},
        409: {"description": "Workspace name already exists."},
        422: {"description": "The organisation is at its workspace quota."},
    },
)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    access: OwnerAccess,
    session: DbSession,
    service: WorkspaceServiceDep,
    audit: AuditTrail,
) -> WorkspaceRead:
    """Create a workspace in the caller's organisation (owner only)."""
    workspace = await service.create_workspace(
        organization_id=access.tenant_id,
        name=payload.name,
        max_workspaces=await load_workspace_quota(session, access.tenant_id),
    )
    await audit.record(
        AuditEvent.WORKSPACE_CREATED,
        target_type="workspace",
        target_id=workspace.id,
        metadata={"name": payload.name},
    )
    return workspace


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_owner_only],
    responses={
        204: {"description": "Workspace and its stored tokens deleted."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Owner role required."},
        404: {"description": "No such workspace in this organisation."},
    },
)
async def delete_workspace(
    workspace_id: PathWorkspaceId,
    access: OwnerAccess,
    service: WorkspaceServiceDep,
    audit: AuditTrail,
) -> None:
    """Delete one of the organisation's workspaces and its WB tokens."""
    await service.delete_workspace(workspace_id, organization_id=access.tenant_id)
    # The one event whose subject no longer exists to be asked about, which is
    # the case this table was built for.
    await audit.record(
        AuditEvent.WORKSPACE_DELETED,
        target_type="workspace",
        target_id=workspace_id,
    )


@router.get(
    "/{workspace_id}/tokens",
    response_model=WorkspaceTokensStatus,
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "Which WB surfaces have a token configured."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Owner role required."},
        404: {"description": "No such workspace in this organisation."},
    },
)
async def get_token_status(
    workspace_id: PathWorkspaceId,
    access: OwnerAccess,
    service: WorkspaceServiceDep,
) -> WorkspaceTokensStatus:
    """Report the workspace's per-surface token configuration (owner only).

    Token *values* are never returned — only which surfaces are configured.
    """
    return await service.token_status(workspace_id, organization_id=access.tenant_id)


@router.put(
    "/{workspace_id}/tokens",
    response_model=WorkspaceTokensStatus,
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "Tokens updated; resulting configuration status."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "Owner role required."},
        404: {"description": "No such workspace in this organisation."},
        422: {"description": "Token kind not valid for this workspace's mode."},
    },
)
async def set_tokens(
    workspace_id: PathWorkspaceId,
    payload: WorkspaceTokensUpdateRequest,
    access: OwnerAccess,
    service: WorkspaceServiceDep,
    audit: AuditTrail,
) -> WorkspaceTokensStatus:
    """Set/rotate the workspace's WB tokens (owner only).

    Partial update: omitted surfaces are untouched; an empty string deletes
    the stored token for that surface. Values are Fernet-encrypted at rest.
    """
    status_after = await service.set_tokens(workspace_id, payload, organization_id=access.tenant_id)
    # WHICH surfaces were touched, never what they were set to. The values are
    # Fernet-encrypted at rest precisely so they exist in one place; copying one
    # into an audit row in the clear would undo that in the row that is kept
    # longest.
    await audit.record(
        AuditEvent.WB_TOKEN_ROTATED,
        target_type="workspace",
        target_id=workspace_id,
        metadata={"kinds": sorted(payload.model_dump(exclude_unset=True))},
    )
    return status_after
