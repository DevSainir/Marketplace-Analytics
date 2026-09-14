"""HTTP surface of the Organizations module.

Four groups, each behind a different guard, and the guard is the whole story of
who the route is for:

* ``/me`` and ``/activate`` and ``/invitations/mine`` — behind ``CurrentAccess``
  only, because a freshly registered account with no organisation MUST be able
  to reach them. They are the two doors in, plus the response that tells the
  SPA which door to show.
* ``/members``, ``/invitations`` — behind ``OwnerAccess``: widening or narrowing
  access to a company is the owner's alone.
* ``/codes`` — behind ``DevAccess``: activation codes are how we get paid.

Routers are pure pass-through; domain errors propagate to the global
``AppError`` handler in ``main.py``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from src.core.deps import DbSession
from src.modules.organizations.deps import (
    ActivationServiceDep,
    AuditRepoDep,
    AuditTrail,
    CurrentAccess,
    DevAccess,
    InvitationServiceDep,
    OrganizationServiceDep,
    OwnerAccess,
    require_dev,
    require_owner,
)
from src.modules.organizations.models import AuditEvent
from src.modules.organizations.routers.members import router as members_router
from src.modules.organizations.schemas import (
    ActivationCodeCreated,
    ActivationCodeCreateRequest,
    ActivationCodeRead,
    ActivationRequest,
    AuditLogEntryRead,
    InvitationAcceptRequest,
    InvitationCreated,
    InvitationCreateRequest,
    InvitationRead,
    MeResponse,
    OrganizationRead,
    OrganizationRenameRequest,
    PendingInvitation,
)
from src.modules.organizations.services import resolve_access
from src.modules.organizations.services.audit import read_trail
from src.modules.users.contract import ConfirmedUser, CurrentUser

router = APIRouter(prefix="/v1/organizations", tags=["Organizations"])

# The owner's member surface, mounted here so it inherits the prefix.
router.include_router(members_router)

#: Route-level guards, declared once so a route cannot pick the wrong one by
#: retyping it.
_owner_only = Depends(require_owner)
_dev_only = Depends(require_dev)


# --------------------------------------------------------------------------- #
# Open to any authenticated account (including one with no organisation)
# --------------------------------------------------------------------------- #
@router.get(
    "/me",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The caller's role, organisation and subscription."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def read_me(
    access: CurrentAccess,
    user: CurrentUser,
    service: OrganizationServiceDep,
) -> MeResponse:
    """Return everything the SPA needs to decide what to render.

    Deliberately reachable without an organisation: a ``null`` organisation is
    the answer that tells the client to show the activation screen.
    """
    return await service.describe(access=access, email=user.email)


@router.post(
    "/activate",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Organisation created; the caller is now its owner."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "The code is unknown, already used, or expired."},
        409: {"description": "This account already belongs to an organisation."},
    },
)
async def activate(
    payload: ActivationRequest,
    access: CurrentAccess,
    # ConfirmedUser, not CurrentUser: redeeming a code makes the holder the
    # OWNER of a company, which is the point at which an unproven address stops
    # being harmless (register P1.6). A no-op while confirmation is not
    # required, which is the default.
    user: ConfirmedUser,
    service: ActivationServiceDep,
    audit: AuditTrail,
) -> OrganizationRead:
    """Redeem an activation code — «Ключ активации» on the profile page.

    Creates the organisation, makes the caller its owner and starts the
    subscription, all in this request's transaction.
    """
    organization = await service.redeem(code=payload.code, user_id=access.user_id, email=user.email)
    # The tenant is passed explicitly: the recorder captured this caller's
    # context before the redemption, when they belonged to no organisation.
    await audit.record(
        AuditEvent.ORG_ACTIVATED,
        target_type="organization",
        target_id=organization.id,
        organization_id=organization.id,
    )
    return organization


@router.get(
    "/invitations/mine",
    response_model=list[PendingInvitation],
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Live invitations addressed to the caller's email."},
        401: {"description": "Missing or invalid access token."},
    },
)
async def list_my_invitations(
    user: CurrentUser,
    service: InvitationServiceDep,
) -> list[PendingInvitation]:
    """List invitations waiting for this account — «Вас пригласили».

    Names the inviting organisation and nothing else about it: the caller is
    not a member yet.
    """
    return await service.list_pending_for(email=user.email)


@router.post(
    "/invitations/accept",
    response_model=MeResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Joined; the refreshed session picture is returned."},
        401: {"description": "Missing or invalid access token."},
        403: {"description": "The invitation is invalid, expired, or not yours."},
        409: {"description": "This account already belongs to an organisation."},
    },
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    session: DbSession,
    access: CurrentAccess,
    # Same reasoning as /activate: accepting puts this account inside somebody
    # else's company, with their data behind it.
    user: ConfirmedUser,
    invitations: InvitationServiceDep,
    organizations: OrganizationServiceDep,
    audit: AuditTrail,
) -> MeResponse:
    """Accept an invitation and join its organisation as a manager.

    Returns the same shape as ``/me`` so the SPA can swap straight from the
    «нет организации» screen into the app without a second round trip.
    """
    await invitations.accept(token=payload.token, user_id=access.user_id, email=user.email)
    # Re-resolved rather than patched: `access` was captured BEFORE the join and
    # is now stale in three fields at once. Hand-assembling the new one here
    # would be a second place that has to know how role, tenant and
    # subscription combine — and the first place to drift from `resolve_access`.
    refreshed = await resolve_access(session, user_id=user.id, platform_role=user.role)
    await audit.record(
        AuditEvent.MEMBER_JOINED,
        target_type="membership",
        target_id=user.id,
        organization_id=refreshed.organization_id,
        # Who, by name. A user id names nobody when the trail is read later.
        metadata={"email": user.email},
    )
    return await organizations.describe(access=refreshed, email=user.email)


# --------------------------------------------------------------------------- #
# The owner's surface
# --------------------------------------------------------------------------- #
@router.patch(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "Renamed."},
        403: {"description": "Owner role required."},
    },
)
async def rename_organization(
    payload: OrganizationRenameRequest,
    access: OwnerAccess,
    service: OrganizationServiceDep,
) -> OrganizationRead:
    """Rename the caller's organisation.

    The name starts as the owner's email (nothing to type at activation); this
    is where it becomes the company's actual name.
    """
    return await service.rename(organization_id=access.tenant_id, name=payload.name)


@router.get(
    "/audit-log",
    response_model=list[AuditLogEntryRead],
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "This organisation's own audit trail, newest first."},
        403: {"description": "Owner role required."},
    },
)
async def read_audit_log(
    access: OwnerAccess,
    repo: AuditRepoDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditLogEntryRead]:
    """Return the organisation's audit trail — who did what, and from where.

    Until this existed the trail was write-only from the product's point of
    view: the rows were there, append-only and enforced, and the only way to
    read them was a psql session on the box. That is a fine answer for us at
    02:00 and no answer at all for an owner asking who removed a manager.

    Owner-scoped, and scoped to their **own** organisation with no un-scoped
    variant anywhere beneath it. The one mistake worth designing out of an audit
    trail is showing one customer another customer's.

    `limit` is bounded rather than free: this is the one table that only ever
    grows, so an unbounded read is a slow query waiting for the tenant who has
    been with us longest (register P1.13's reasoning, applied to a read).

    Args:
        access: Owner-level access; supplies the organisation.
        repo: The audit repository.
        limit: How many entries to return, newest first.

    Returns:
        Up to ``limit`` entries.
    """
    entries = await read_trail(repo, organization_id=access.tenant_id, limit=limit)
    return [AuditLogEntryRead.model_validate(entry) for entry in entries]


@router.get(
    "/invitations",
    response_model=list[InvitationRead],
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "Every invitation issued, newest first."},
        403: {"description": "Owner role required."},
    },
)
async def list_invitations(
    access: OwnerAccess,
    service: InvitationServiceDep,
) -> list[InvitationRead]:
    """List the organisation's invitations — pending, accepted and revoked."""
    return await service.list_issued(organization_id=access.tenant_id)


@router.post(
    "/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_owner_only],
    responses={
        201: {"description": "Issued; the response carries the token exactly once."},
        403: {"description": "Owner role required."},
        422: {"description": "The manager quota is full."},
    },
)
async def create_invitation(
    payload: InvitationCreateRequest,
    access: OwnerAccess,
    service: InvitationServiceDep,
    audit: AuditTrail,
) -> InvitationCreated:
    """Invite a manager, by email or as a bare link.

    With ``email`` set the invitation also appears on that account's own
    profile page, so a colleague who already has an account never needs the
    link. The token is returned once and stored hashed.
    """
    invitation = await service.invite(
        organization_id=access.tenant_id,
        owner_user_id=access.user_id,
        email=payload.email,
        valid_for_hours=payload.valid_for_hours,
        access=payload.access,
    )
    # The invitee's address and the grant it carries, never the token: the token
    # is the credential and the response above is the only place it is shown.
    #
    # The grant is here because it is the whole point of an invitation — the
    # access travels WITH it, so "what did this link hand out" is answerable
    # only from this row once the link is spent or revoked.
    await audit.record(
        AuditEvent.MEMBER_INVITED,
        target_type="invitation",
        target_id=invitation.id,
        metadata={
            "email": payload.email,
            "valid_for_hours": payload.valid_for_hours,
            "access_level": payload.access.access_level.value,
            "modules": [m.value for m in payload.access.modules],
        },
    )
    return invitation


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_owner_only],
    responses={
        204: {"description": "Withdrawn (idempotent)."},
        403: {"description": "Owner role required."},
        404: {"description": "No such invitation in this organisation."},
        409: {"description": "Already accepted — remove the member instead."},
    },
)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    access: OwnerAccess,
    service: InvitationServiceDep,
    audit: AuditTrail,
) -> Response:
    """Withdraw an outstanding invitation."""
    revoked_email = await service.revoke(
        organization_id=access.tenant_id, invitation_id=invitation_id
    )
    await audit.record(
        AuditEvent.INVITATION_REVOKED,
        target_type="invitation",
        target_id=invitation_id,
        # The address, so the trail names the link rather than a UUID. Once the
        # row is revoked the list stops showing it, and this is the only place
        # left that says which one it was.
        metadata={"email": revoked_email},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# The dev surface: activation codes
# --------------------------------------------------------------------------- #
@router.post(
    "/codes",
    response_model=ActivationCodeCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_dev_only],
    responses={
        201: {"description": "Generated; the response carries the code exactly once."},
        403: {"description": "Developer role required."},
    },
)
async def create_activation_code(
    payload: ActivationCodeCreateRequest,
    access: DevAccess,
    service: ActivationServiceDep,
    audit: AuditTrail,
) -> ActivationCodeCreated:
    """Generate a single-use activation code to hand to a paying customer."""
    created = await service.generate_code(
        note=payload.note,
        valid_for_days=payload.valid_for_days,
        subscription_days=payload.subscription_days,
        created_by_user_id=access.user_id,
    )
    # The note and the term, never the code itself — the code is a credential
    # that buys a paid account, and this row is readable long after it is spent.
    await audit.record(
        AuditEvent.ACTIVATION_CODE_ISSUED,
        target_type="activation_code",
        target_id=created.id,
        metadata={"note": payload.note, "subscription_days": payload.subscription_days},
    )
    return created


@router.get(
    "/codes",
    response_model=list[ActivationCodeRead],
    status_code=status.HTTP_200_OK,
    dependencies=[_dev_only],
    responses={
        200: {"description": "Every generated code — values are never included."},
        403: {"description": "Developer role required."},
    },
)
async def list_activation_codes(service: ActivationServiceDep) -> list[ActivationCodeRead]:
    """List generated codes, newest first, with what each one became."""
    return await service.list_codes()


__all__ = ["router"]
