"""Dev-only routes that open another company's кабинет to a head, read-only.

``DevAccess`` on every route, and nothing weaker would do: a grant crosses the
one boundary the rest of the platform exists to hold — one company reading
another's кабинет. Neither company's owner may decide that, so ``OwnerAccess``
is wrong, and it is a platform decision rather than a tenant one.

These routes touch ``workspaces.workspace_guests`` and ``workspaces.workspaces``
only — both outside the row-level-security set — so they bind no workspace.
What a grant then opens is enforced in ``deps.get_current_workspace_id``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from src.core.deps import DbSession
from src.modules.organizations.contract import AuditEvent, AuditTrail, DevAccess
from src.modules.workspaces.guests import (
    grant_guest,
    list_grantable_workspaces,
    list_guests,
    revoke_guest,
)
from src.modules.workspaces.schemas import (
    GuestGrantRead,
    GuestGrantRequest,
    GuestWorkspaceOption,
)

#: Mounted by ``main.py`` next to the workspaces router rather than inside it,
#: so the path is whole wherever the app's routes are walked.
router = APIRouter(prefix="/v1/workspaces/guests", tags=["Workspaces"])

_DEV_ONLY_RESPONSES: dict[int | str, dict[str, str]] = {
    401: {"description": "Missing or invalid access token."},
    403: {"description": "Developer role required."},
}


@router.get(
    "",
    response_model=list[GuestGrantRead],
    status_code=status.HTTP_200_OK,
    responses=_DEV_ONLY_RESPONSES,
)
async def list_guest_grants(_dev: DevAccess, session: DbSession) -> list[GuestGrantRead]:
    """Every standing grant — who may read which кабинет of another company."""
    return await list_guests(session)


@router.get(
    "/workspaces",
    response_model=list[GuestWorkspaceOption],
    status_code=status.HTTP_200_OK,
    responses=_DEV_ONLY_RESPONSES,
)
async def list_grantable(_dev: DevAccess, session: DbSession) -> list[GuestWorkspaceOption]:
    """Every кабинет on the platform, id and name only, for the grant form.

    ``DevAccess``: the list names every customer, which is a platform fact no
    tenant may see — and the dev who may grant any of them already can.
    """
    return await list_grantable_workspaces(session)


@router.post(
    "",
    response_model=GuestGrantRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_DEV_ONLY_RESPONSES,
        404: {"description": "No such account or кабинет."},
        409: {"description": "The account is a dev."},
    },
)
async def grant_guest_access(
    payload: GuestGrantRequest,
    access: DevAccess,
    session: DbSession,
    audit: AuditTrail,
) -> GuestGrantRead:
    """Open a кабинет to an account, read-only; the account becomes ``head``."""
    grant = await grant_guest(
        session,
        email=payload.email,
        workspace_name=payload.workspace_name,
        granted_by=access.user_id,
    )
    await audit.record(
        AuditEvent.WORKSPACE_GUEST_GRANTED,
        target_type="workspace",
        target_id=grant.workspace_id,
        metadata={"grant_id": str(grant.id)},
    )
    return grant


@router.delete(
    "/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_DEV_ONLY_RESPONSES, 404: {"description": "No such grant."}},
)
async def revoke_guest_access(
    grant_id: uuid.UUID,
    _dev: DevAccess,
    session: DbSession,
    audit: AuditTrail,
) -> None:
    """Close one grant. The account keeps the ``head`` role, which alone opens nothing."""
    user_id = await revoke_guest(session, grant_id)
    await audit.record(
        AuditEvent.WORKSPACE_GUEST_REVOKED,
        target_type="user",
        target_id=user_id,
        metadata={"grant_id": str(grant_id)},
    )
