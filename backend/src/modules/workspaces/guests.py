"""Guest access: a head reading another company's workspace.

A user belongs to at most one organisation, and every workspace is reached
through the caller's own one. The single exception is here: a dev may open a
named workspace to an account holding the ``head`` platform role, and that head
may then switch into it and **read** — the switcher lists it, every GET
answers, and every write is refused where the workspace is resolved
(``deps.get_current_workspace_id``). Nothing about the owning company changes:
it does not see the head, its members and subscription are untouched, and the
head never reaches its tokens, members or billing (those routes check the
organisation, not the grant).

Granting promotes an ordinary account to ``head`` on the way, so one call does
the whole job. Revoking leaves the role alone: with no grants it opens nothing.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.users.contract import ROLE_DEV, load_emails, load_role, promote_to_head
from src.modules.workspaces.repos import WorkspaceGuestRepository, WorkspaceRepository
from src.modules.workspaces.schemas import GuestGrantRead, GuestWorkspaceOption, WorkspaceRead


async def list_guest_workspaces(
    guests: WorkspaceGuestRepository, *, user_id: uuid.UUID, organization_id: uuid.UUID | None
) -> list[WorkspaceRead]:
    """The workspaces granted to one head, minus any their own company owns.

    A grant on a workspace of the head's own organisation is harmless but
    would list it twice; the own entry wins, since it is the one they may
    write in.
    """
    return [
        WorkspaceRead.model_validate(ws).model_copy(update={"is_guest": True})
        for ws in await guests.list_workspaces_for_user(user_id)
        if ws.organization_id != organization_id
    ]


async def list_guests(session: AsyncSession) -> list[GuestGrantRead]:
    """Every grant on the platform, for the dev who manages them."""
    rows = await WorkspaceGuestRepository(session).list_all()
    emails = await load_emails(session, {guest.user_id for guest, _ in rows})
    return [
        GuestGrantRead(
            id=guest.id,
            email=emails.get(guest.user_id, ""),
            workspace_id=guest.workspace_id,
            workspace_name=name,
            created_at=guest.created_at,
        )
        for guest, name in rows
    ]


async def list_grantable_workspaces(session: AsyncSession) -> list[GuestWorkspaceOption]:
    """Every workspace on the platform, by name — what the dev's grant form offers."""
    workspaces = await WorkspaceRepository(session).list_all()
    return sorted(
        (GuestWorkspaceOption(id=ws.id, name=ws.name) for ws in workspaces),
        key=lambda option: option.name.lower(),
    )


async def grant_guest(
    session: AsyncSession, *, email: str, workspace_name: str, granted_by: uuid.UUID
) -> GuestGrantRead:
    """Open a workspace to an account, read-only, promoting it to ``head``.

    Idempotent: granting what is already granted returns the standing grant.

    Raises:
        NotFoundError: No such account, or no such workspace. One message for
            both would hide which one the dev mistyped, and this route is
            behind the dev role, so there is no oracle to protect.
        ConflictError: The account is a dev — it already has the wider role,
            and a grant would sit on it doing nothing.
    """
    workspace = await WorkspaceRepository(session).get_by_name(workspace_name.strip())
    if workspace is None:
        raise NotFoundError("No workspace with this name.")
    if await load_role(session, email) == ROLE_DEV:
        raise ConflictError("A developer needs no guest access.")
    user_id = await promote_to_head(session, email)
    if user_id is None:
        raise NotFoundError("No account with this email.")
    guest = await WorkspaceGuestRepository(session).add(
        workspace_id=workspace.id, user_id=user_id, granted_by=granted_by
    )
    return GuestGrantRead(
        id=guest.id,
        email=email.strip().lower(),
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        created_at=guest.created_at,
    )


async def revoke_guest(session: AsyncSession, grant_id: uuid.UUID) -> uuid.UUID:
    """Close one grant; return the account it was held by.

    Raises:
        NotFoundError: No grant with that id.
    """
    guest = await WorkspaceGuestRepository(session).remove(grant_id)
    if guest is None:
        raise NotFoundError("Guest access not found.")
    return guest.user_id


__all__ = [
    "grant_guest",
    "list_grantable_workspaces",
    "list_guest_workspaces",
    "list_guests",
    "revoke_guest",
]
