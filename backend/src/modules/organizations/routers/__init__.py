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

from fastapi import APIRouter, Depends, Response, status

from src.core.deps import DbSession
from src.modules.organizations.deps import (
    ActivationServiceDep,
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
from src.modules.organizations.schemas import (
    ActivationCodeCreated,
    ActivationCodeCreateRequest,
    ActivationCodeRead,
    ActivationRequest,
    InvitationAcceptRequest,
    InvitationCreated,
    InvitationCreateRequest,
    InvitationRead,
    MemberRead,
    MeResponse,
    OrganizationRead,
    OrganizationRenameRequest,
    PendingInvitation,
)
from src.modules.organizations.services import resolve_access
from src.modules.users.contract import CurrentUser

router = APIRouter(prefix="/v1/organizations", tags=["Organizations"])

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
    user: CurrentUser,
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
    user: CurrentUser,
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
    "/members",
    response_model=list[MemberRead],
    status_code=status.HTTP_200_OK,
    dependencies=[_owner_only],
    responses={
        200: {"description": "The organisation's members, owner first."},
        403: {"description": "Owner role required."},
    },
)
async def list_members(
    access: OwnerAccess,
    service: OrganizationServiceDep,
) -> list[MemberRead]:
    """List the organisation's members."""
    return await service.list_members(organization_id=access.tenant_id)


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_owner_only],
    responses={
        204: {"description": "Member removed; their account keeps existing."},
        403: {"description": "Owner role required."},
        404: {"description": "No such member in this organisation."},
        422: {"description": "The owner cannot be removed."},
    },
)
async def remove_member(
    user_id: uuid.UUID,
    access: OwnerAccess,
    service: OrganizationServiceDep,
    audit: AuditTrail,
) -> Response:
    """Remove a manager from the organisation.

    This — not revoking their invitation — is what actually withdraws access
    once someone has joined.
    """
    await service.remove_member(organization_id=access.tenant_id, user_id=user_id)
    await audit.record(
        AuditEvent.MEMBER_REMOVED,
        target_type="membership",
        target_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
        valid_for_days=payload.valid_for_days,
    )
    # The invitee's address, never the token: the token is the credential and
    # the response above is the only place it is ever shown.
    await audit.record(
        AuditEvent.MEMBER_INVITED,
        target_type="invitation",
        target_id=invitation.id,
        metadata={"email": payload.email},
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
    await service.revoke(organization_id=access.tenant_id, invitation_id=invitation_id)
    await audit.record(
        AuditEvent.INVITATION_REVOKED,
        target_type="invitation",
        target_id=invitation_id,
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
