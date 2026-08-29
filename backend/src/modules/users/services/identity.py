"""Resolving account ids to the facts другие modules need about them."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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


__all__ = ["load_emails"]
