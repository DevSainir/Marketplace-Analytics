"""HTTP presentation layer for the Workspaces module.

Every route here is scoped to the caller's own organisation, and the guards say
who may do what:

* **listing** needs only membership — a manager has to be able to switch between
  the workspaces they work in;
* **creating, deleting and managing WB tokens** need ``owner``. These change
  what the company IS and what it costs, and a WB token is the credential to a
  seller's live account;
* **guest grants** (``/guests``, in ``guest_routers``) need ``dev``: they open
  another company's кабинет, read-only, to a head.

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
    WritingAccess,
    load_workspace_quota,
    require_owner,
)
from src.modules.workspaces.backfill import read_progress
from src.modules.workspaces.bootstrap import enqueue_catalogue_bootstrap, newly_reachable
from src.modules.workspaces.deps import (
    CurrentWorkspaceId,
    PathWorkspaceId,
    WorkspaceGuestRepoDep,
    WorkspaceServiceDep,
)
from src.modules.workspaces.guests import list_guest_workspaces
from src.modules.workspaces.schemas import (
    BackfillStatusResponse,
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceRead,
    WorkspaceSettingsUpdate,
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
    guests: WorkspaceGuestRepoDep,
) -> WorkspaceListResponse:
    """List the workspaces the caller may switch between.

    For a head, that is their own company's кабинеты followed by the ones a
    dev opened to them in other companies, flagged ``is_guest``.
    """
    # A guest with no company of their own has no кабинеты of their own.
    items = (
        []
        if access.organization_id is None
        else await service.list_workspaces(organization_id=access.organization_id)
    )
    if access.is_head:
        items += await list_guest_workspaces(
            guests, user_id=access.user_id, organization_id=access.organization_id
        )
    return WorkspaceListResponse(items=items)


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


@router.patch(
    "/current/settings",
    response_model=WorkspaceRead,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The workspace with its settings changed."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "A read-only role, or a guest in another company's кабинет."},
        404: {"description": "No such workspace in this organisation."},
    },
)
async def update_workspace_settings(
    workspace_id: CurrentWorkspaceId,
    access: WritingAccess,
    body: WorkspaceSettingsUpdate,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    """Change what the кабинет shows to everyone in it.

    ``WritingAccess``, not ``MemberAccess``: the setting changes the page for
    every member, so a read-only manager must not flip it for the owner. Not
    ``OwnerAccess`` either — it is a display choice, not the company's
    credentials or bill, and the managers who read advertising are the ones
    who know whether the seller has bonuses.

    The кабинет is the active one, from ``X-Workspace-Id``
    (``CurrentWorkspaceId``), not a path id, whose binder is owner-only. That
    binder answers 404 for another company's кабинет and lets a guest only
    read. Not audited: the setting hides or shows a figure and moves no money
    and no access.
    """
    return await service.update_settings(
        workspace_id, organization_id=access.tenant_id, ads_show_bonus=body.ads_show_bonus
    )


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

    Storing a token that makes a harvest surface reachable also enqueues a
    catalogue discovery for it, so a seller who has just connected WB sees their
    SKUs within minutes instead of after the next nightly harvest — and walks
    only the history lanes that surface feeds. A surface nothing reads, such as
    «Вопросы и отзывы», enqueues nothing. The enqueue is best-effort and
    debounced per workspace; it can neither fail this request nor be provoked
    into a second run by re-saving the same token.
    """
    # Read the configured set BEFORE the write, so the harvest below can be
    # triggered by a surface becoming available rather than by the form being
    # saved. Re-pasting a token that was already there changes nothing the
    # catalogue could not already see, and must not spend the WB rate budget.
    before = await service.token_status(workspace_id, organization_id=access.tenant_id)
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
    if surfaces := newly_reachable(before.configured, status_after.configured):
        # A surface this workspace could not reach a moment ago is now reachable
        # — which for a newly onboarded seller is every surface, over an empty
        # catalogue. Only surfaces something reads count: a `feedback` token
        # added to an established кабинет once re-walked its whole history
        # (2026-10-02). Discovery is what turns that into something to look at, and
        # before this call the only thing that ran it was the 06:00 MSK nightly
        # pass. Deliberately not awaited for a result: the seller's request is
        # "store my token", and it succeeds whether or not the queue accepts the
        # harvest (see :mod:`~src.modules.workspaces.bootstrap`).
        await enqueue_catalogue_bootstrap(workspace_id, surfaces)
    return status_after


@router.get(
    "/{workspace_id}/backfill",
    response_model=BackfillStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Per-lane progress of this workspace's history backfill."},
        401: {"description": "Missing or invalid access token."},
        404: {"description": "No such workspace in this organisation."},
    },
)
async def get_backfill_status(
    workspace_id: PathWorkspaceId,
    access: MemberAccess,
    session: DbSession,
) -> BackfillStatusResponse:
    """Report how far this workspace's history backfill has got, per lane.

    Any MEMBER may read it, not just an owner: it is rendered in the profile as
    the answer to «почему тут пусто», and a manager who cannot see it is left
    with a blank product page and no explanation. It exposes only counters and
    a Russian status line — no token, no WB response, nothing tenant-specific
    beyond the workspace the caller was already proved to belong to.

    Returns an empty lane list for a workspace that has never been backfilled,
    rather than 404: "nothing is running" is the honest answer for every
    workspace created before this existed.
    """
    return await read_progress(session, workspace_id)
