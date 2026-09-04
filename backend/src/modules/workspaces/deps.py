"""Dependency-injection wiring for the Workspaces module.

Besides the usual repository -> service graph, this module owns the
**workspace-context dependency**: every tenant-scoped route resolves the
``X-Workspace-Id`` request header into a validated workspace id.

The header is a *claim*, and it is checked against the caller's own
organisation on every request. Until 2026-08-27 it was checked only for
existence, which meant any authenticated account could read and write any
seller's data by changing one header value — the header WAS the tenancy. Now
the workspace must exist AND belong to the organisation the caller is a member
of, and a workspace belonging to anyone else answers 404, indistinguishable
from one that was deleted.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, status
from fastapi.exceptions import HTTPException

from src.core.deps import DbSession
from src.core.logcontext import bind_workspace
from src.core.tenancy import set_workspace_context
from src.modules.organizations.contract import MemberAccess, OwnerAccess
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
    access: MemberAccess,
    workspace_repo: WorkspaceRepoDep,
    session: DbSession,
    x_workspace_id: Annotated[
        str | None,
        Header(
            alias=WORKSPACE_HEADER,
            description="Active workspace id (UUID) the request operates in.",
        ),
    ] = None,
) -> uuid.UUID:
    """Resolve the ``X-Workspace-Id`` header into a workspace the caller owns.

    This is the platform's tenancy choke point. ``MemberAccess`` is what makes
    it one: it both authenticates the caller and produces the organisation the
    header is checked against, so there is no ordering in which the check can
    be skipped.

    A workspace owned by another organisation is reported as **404, not 403**.
    A 403 would confirm the id names a real workspace, which turns this
    endpoint into an oracle for other sellers' workspace ids — and those ids
    are the only thing standing between an attacker and a tenant's data on
    every other route.

    It is also where the tenant is announced to PostgreSQL, for the row-level
    security policies (register P2.5) — **after** the ownership check and never
    before it. Binding a tenant the caller has not been shown to belong to would
    hand the database the very claim this function exists to verify.

    Args:
        access: The caller's resolved access; guaranteed to have an
            organisation by ``MemberAccess``.
        workspace_repo: Workspace repository bound to the request session.
        session: The request's session, so the tenant can be bound to its
            transaction.
        x_workspace_id: The raw header value.

    Returns:
        The validated workspace UUID, proven to belong to the caller's tenant.

    Raises:
        HTTPException: ``400`` when the header is missing or not a UUID;
            ``404`` when the workspace does not exist OR belongs to another
            organisation (deliberately the same answer).
    """
    if not x_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не выбрано рабочее пространство.",
        )
    try:
        workspace_id = uuid.UUID(x_workspace_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Некорректный идентификатор рабочего пространства.",
        ) from exc
    workspace = await workspace_repo.get_by_id(workspace_id)
    if workspace is None or workspace.organization_id != access.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Рабочее пространство не найдено.",
        )
    # Proven to belong to the caller — only now is it safe to tell the database,
    # or the logs. Both announcements sit behind the same check for the same
    # reason: recording a tenant the caller has not been shown to belong to
    # would put the claim this function exists to verify into the evidence
    # somebody would later use to verify it (register P2.2/P2.5).
    await set_workspace_context(session, workspace_id)
    bind_workspace(workspace_id)
    return workspace_id


async def get_path_workspace_id(
    workspace_id: uuid.UUID,
    access: OwnerAccess,
    workspace_repo: WorkspaceRepoDep,
    session: DbSession,
) -> uuid.UUID:
    """Validate a workspace taken from the URL path, and bind it as the tenant.

    The sibling of :func:`get_current_workspace_id` for the owner-only routes
    that address a workspace by path (`/{workspace_id}/tokens`) rather than by
    the `X-Workspace-Id` header. Those routes already scope correctly — the
    services take `organization_id` and every query filters on it — so this adds
    no authorization that was missing. What it adds is the **binding**: without
    passing through here there is nowhere to tell PostgreSQL which tenant is
    asking, and a row-level-security policy on `workspace_tokens` would make
    every one of those requests raise (register P2.5).

    The 404-not-403 rule is the same one, and for the same reason: a 403 would
    confirm the id names a real workspace, turning the path into an oracle for
    other sellers' workspace ids.

    This does look the workspace up a second time — the service that follows
    scopes its own query too. That duplication is kept: the service's check
    protects callers that are not routes (a script, a task), and dropping it to
    save one primary-key lookup on three owner-only admin screens would trade a
    real guard for nothing measurable.

    Args:
        workspace_id: The path parameter. Named to match the route's own, which
            is what lets FastAPI hand it to this dependency.
        access: Owner-level access, which supplies the organisation to check
            against.
        workspace_repo: Workspace repository bound to the request session.
        session: The request's session, so the tenant can be bound to it.

    Returns:
        The validated workspace id, proven to belong to the caller's tenant.

    Raises:
        HTTPException: ``404`` when the workspace does not exist or belongs to
            another organisation — deliberately the same answer.
    """
    workspace = await workspace_repo.get_by_id(workspace_id)
    if workspace is None or workspace.organization_id != access.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Рабочее пространство не найдено.",
        )
    await set_workspace_context(session, workspace_id)
    return workspace_id


#: A path-addressed workspace, validated against the caller's organisation and
#: bound as the transaction's tenant.
PathWorkspaceId = Annotated[uuid.UUID, Depends(get_path_workspace_id)]


#: Injectable, validated active-workspace id for tenant-scoped routes.
CurrentWorkspaceId = Annotated[uuid.UUID, Depends(get_current_workspace_id)]
