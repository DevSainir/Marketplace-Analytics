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
    """
    member = await service.set_member_access(
        organization_id=access.tenant_id,
        user_id=user_id,
        access_level=payload.access_level,
        modules=payload.modules,
    )
    await audit.record(
        AuditEvent.MEMBER_ACCESS_CHANGED,
        target_type="membership",
        target_id=user_id,
        metadata={
            "access_level": member.access_level.value,
            "modules": [m.value for m in member.modules],
        },
    )
    return member


__all__ = ["router"]
