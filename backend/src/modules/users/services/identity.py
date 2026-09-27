"""Resolving account ids to the facts другие modules need about them."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.users.models import ROLE_HEAD, ROLE_USER
from src.modules.users.repos import UserRepository


async def load_emails(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Resolve account ids to their login emails.

    A module-level function (not a service method) for the same reason the
    workspaces module has one: the consumer is another module, reached through
    ``contract.py``, and it needs a fact about identity rather than a piece of
    authentication behaviour. Today's caller is the organisation member list,
    which holds user ids and has to print names.

    Args:
        session: An open async session (caller owns the transaction).
        user_ids: The accounts to resolve.

    Returns:
        ``{user_id: email}``; unknown ids are absent rather than raising, since
        a membership whose account was deleted is a row to skip, not an error.
    """
    return await UserRepository(session).emails_by_id(user_ids)


async def promote_to_head(session: AsyncSession, email: str) -> uuid.UUID | None:
    """Give an account the ``head`` platform role, and return its id.

    Only an ordinary ``user`` is promoted. A ``dev`` keeps its role — it is
    the wider one, and demoting it by granting it a кабинет would be a
    surprise nobody asked for — and so ends up with a grant that does nothing,
    which is why the caller refuses a dev before it gets here.

    Args:
        session: An open async session (caller owns the transaction).
        email: The account's login email, in any case.

    Returns:
        The account id, or ``None`` when no account has that email.
    """
    user = await UserRepository(session).get_by_email(email.strip().lower())
    if user is None:
        return None
    if user.role == ROLE_USER:
        user.role = ROLE_HEAD
        await session.flush()
    return user.id


async def load_role(session: AsyncSession, email: str) -> str | None:
    """Return an account's platform role by email, or ``None`` if absent."""
    user = await UserRepository(session).get_by_email(email.strip().lower())
    return user.role if user is not None else None


__all__ = ["load_emails", "load_role", "promote_to_head"]
