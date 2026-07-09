"""Data-access layer for the Users module.

Repositories are the *only* code permitted to build and execute SQLAlchemy
statements for this module. Services depend on these classes and never touch the
:class:`AsyncSession` query API directly, satisfying the Clean Architecture
boundary "business logic has no direct database access".
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.users.models import RefreshToken, User


class UserRepository:
    """CRUD operations for :class:`User` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return a user by primary key, or ``None`` if absent."""
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return a user by unique email, or ``None`` if absent.

        Args:
            email: The normalized login email.

        Returns:
            The matching :class:`User`, or ``None`` when no row exists.
        """
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, *, email: str, hashed_password: str) -> User:
        """Insert and flush a new user, returning the populated instance.

        Args:
            email: Unique login email.
            hashed_password: Pre-computed bcrypt digest.

        Returns:
            The persisted :class:`User` with its generated id populated.
        """
        user = User(email=email, hashed_password=hashed_password)
        self._session.add(user)
        await self._session.flush()
        return user


class RefreshTokenRepository:
    """CRUD + family-revocation operations for :class:`RefreshToken` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def create(
        self,
        *,
        token_id: uuid.UUID,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        parent_id: uuid.UUID | None = None,
    ) -> RefreshToken:
        """Persist a newly issued refresh-token row.

        Args:
            token_id: UUIDv7 id (also the JWT ``jti``).
            user_id: Owning user's id.
            family_id: Login-lineage identifier shared across the chain.
            token_hash: SHA-256 digest of the opaque refresh secret.
            expires_at: Absolute expiry (UTC).
            parent_id: Superseded token id, or ``None`` for a fresh login.

        Returns:
            The flushed :class:`RefreshToken` instance.
        """
        token = RefreshToken(
            id=token_id,
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            expires_at=expires_at,
            parent_id=parent_id,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Return a refresh-token row by its secret hash, or ``None``."""
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_used(self, token_id: uuid.UUID) -> None:
        """Flag a single token as consumed (rotated)."""
        stmt = update(RefreshToken).where(RefreshToken.id == token_id).values(is_used=True)
        await self._session.execute(stmt)

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke every non-revoked refresh token owned by a user.

        Invoked by the breach-detection flow to force a global logout across all
        devices when a consumed token is replayed.

        Args:
            user_id: The user whose entire session set must be invalidated.

        Returns:
            The number of rows revoked.
        """
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Revoke every non-revoked token in a single login family/lineage.

        Args:
            family_id: The lineage identifier to invalidate.

        Returns:
            The number of rows revoked.
        """
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)
