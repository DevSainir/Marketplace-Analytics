"""Dependency-injection wiring for the Workspaces module.

Besides the usual repository -> service graph, this module owns the
**workspace-context dependency**: every tenant-scoped route resolves the
``X-Workspace-Id`` request header into a validated workspace id. The frontend
sends the header on all API requests; the backend never trusts it blindly —
the workspace must exist, and the caller must be authenticated.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, status
from fastapi.exceptions import HTTPException

from src.core.deps import CurrentUserId, DbSession
from src.modules.workspaces.repos import WorkspaceRepository, WorkspaceTokenRepository
from src.modules.workspaces.services import WorkspaceService

#: Request header carrying the caller's active workspace id (a UUID).
WORKSPACE_HEADER: str = "X-Workspace-Id"


def get_workspace_repo(session: DbSession) -> WorkspaceRepository:
    """Provide a :class:`WorkspaceRepository` bound to the request session."""
    return WorkspaceRepository(session)


def get_workspace_token_repo(session: DbSession) -> WorkspaceTokenRepository:
    """Provide a :class:`WorkspaceTokenRepository` bound to the request session."""
    return WorkspaceTokenRepository(session)


WorkspaceRepoDep = Annotated[WorkspaceRepository, Depends(get_workspace_repo)]
WorkspaceTokenRepoDep = Annotated[WorkspaceTokenRepository, Depends(get_workspace_token_repo)]


def get_workspace_service(
    workspace_repo: WorkspaceRepoDep,
    token_repo: WorkspaceTokenRepoDep,
) -> WorkspaceService:
    """Compose the :class:`WorkspaceService` from its repository collaborators."""
    return WorkspaceService(workspace_repo=workspace_repo, token_repo=token_repo)


#: Clean, injectable service type consumed by the workspace routers.
WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


async def get_current_workspace_id(
    _user_id: CurrentUserId,
    workspace_repo: WorkspaceRepoDep,
    x_workspace_id: Annotated[
        str | None,
        Header(
            alias=WORKSPACE_HEADER,
            description="Active workspace id (UUID) the request operates in.",
        ),
    ] = None,
) -> uuid.UUID:
    """Resolve and validate the ``X-Workspace-Id`` header into a workspace id.

    Authentication is a prerequisite (``_user_id``): the workspace context is
    meaningless for anonymous callers, and validating the header before auth
    would leak workspace existence. Any authenticated user may currently use
    any workspace — per-user membership arrives with the future role system.

    Args:
        _user_id: The authenticated caller (validated, then unused for now).
        workspace_repo: Workspace repository bound to the request session.
        x_workspace_id: The raw header value.

    Returns:
        The validated workspace UUID.

    Raises:
        HTTPException: ``400`` when the header is missing or not a UUID;
            ``404`` when no such workspace exists (e.g. it was deleted while
            the client still had it selected).
    """
    if not x_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing {WORKSPACE_HEADER} header.",
        )
    try:
        workspace_id = uuid.UUID(x_workspace_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{WORKSPACE_HEADER} header is not a valid UUID.",
        ) from exc
    if await workspace_repo.get_by_id(workspace_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    return workspace_id


#: Injectable, validated active-workspace id for tenant-scoped routes.
CurrentWorkspaceId = Annotated[uuid.UUID, Depends(get_current_workspace_id)]
