"""The owner's member surface: who is in the company, and what they may reach.

Split out of the module's ``__init__`` when the access grant arrived — three
routes about one subject, in the largest file of the module.

Every route here is owner-only. Narrowing or widening what a colleague may see
is the one decision that must not be delegated to the colleague.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from src.modules.organizations.deps import (
    AuditTrail,
    OrganizationServiceDep,
    OwnerAccess,
    require_owner,
)
from src.modules.organizations.models import AuditEvent
from src.modules.organizations.schemas import MemberAccessUpdateRequest, MemberRead

router = APIRouter(dependencies=[Depends(require_owner)])


@router.get(
    "/members",
    response_model=list[MemberRead],
    status_code=status.HTTP_200_OK,
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


@router.patch(
    "/members/{user_id}/access",
    response_model=MemberRead,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "The member's grant as it now stands."},
        403: {"description": "Owner role required."},
        404: {"description": "No such member in this organisation."},
        422: {"description": "The owner's own access cannot be changed."},
    },
)
async def set_member_access(
    user_id: uuid.UUID,
    payload: MemberAccessUpdateRequest,
    access: OwnerAccess,
    service: OrganizationServiceDep,
    audit: AuditTrail,
) -> MemberRead:
    """Set what one manager may do, and which sections they may open.

    The whole grant is sent every time rather than patched field by field: the
    owner is looking at a form showing the current state, and a partial update
    from a stale form would silently keep a module they had just switched off.

    Recorded in the audit trail with the resulting grant, because "who could
    read the P&L in July" is a question that gets asked after somebody leaves.

    **Only when something actually changed.** Opening the form and pressing
    save writes the same grant back, and recording that produced entries saying
    «Изменён доступ» about a change that did not happen — which turns a trail
    meant to be read into one that has to be searched. The comparison is made
    here rather than in the service because "was this worth recording" is a
    question about the audit trail, not about the membership.
    """
    before = await service.member_grant(organization_id=access.tenant_id, user_id=user_id)
    member = await service.set_member_access(
        organization_id=access.tenant_id,
        user_id=user_id,
        access_level=payload.access_level,
        modules=payload.modules,
    )
    after = (member.access_level.value, [m.value for m in member.modules])
    if before != after:
        await audit.record(
            AuditEvent.MEMBER_ACCESS_CHANGED,
            target_type="membership",
            target_id=user_id,
            metadata={
                # The address as well as the grant: the trail is read long after
                # the fact, and a user id names nobody. It is the tenant's own
                # member, so nothing crosses an organisation by being here.
                "email": member.email,
                "access_level": after[0],
                "modules": after[1],
                "previous_access_level": before[0] if before else None,
                "previous_modules": before[1] if before else None,
            },
        )
    return member


__all__ = ["router"]
