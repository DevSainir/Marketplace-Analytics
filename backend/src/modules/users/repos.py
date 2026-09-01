"""Data-access layer for the Users module.

Repositories are the *only* code permitted to build and execute SQLAlchemy
statements for this module. Services depend on these classes and never touch the
:class:`AsyncSession` query API directly, satisfying the Clean Architecture
boundary "business logic has no direct database access".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.users.models import RefreshToken, User, VerificationCode


class UserRepository:
    """CRUD operations for :class:`User` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return a user by primary key, or ``None`` if absent."""
        return await self._session.get(User, user_id)

    async def emails_by_id(self, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Return ``{user_id: email}`` for the given accounts.

        One statement rather than a lookup per row: the caller is an
        organisation's member list, and a per-member query would make the page
        cost scale with the team.

        Args:
            user_ids: Accounts to resolve. An empty set short-circuits.

        Returns:
            A mapping; ids with no row are simply absent.
        """
        if not user_ids:
            return {}
        stmt = select(User.id, User.email).where(User.id.in_(user_ids))
        result = await self._session.execute(stmt)
        return {row.id: row.email for row in result}

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

    async def mark_email_confirmed(self, user: User) -> None:
        """Record that this account's address has been proven.

        Idempotent by intent: re-confirming keeps the ORIGINAL timestamp, so
        "when was this address proven" cannot be reset by asking again. During
        an incident the first answer is the one that matters.

        Args:
            user: The account to stamp.
        """
        if user.email_confirmed_at is None:
            user.email_confirmed_at = datetime.now(UTC)
            await self._session.flush()

    async def set_password(self, user: User, *, hashed_password: str) -> None:
        """Replace the account's password digest.

        Args:
            user: The account.
            hashed_password: The new bcrypt digest.
        """
        user.hashed_password = hashed_password
        await self._session.flush()

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

    async def consume(self, token_id: uuid.UUID) -> bool:
        """Atomically flag a token as consumed (rotated), exactly once.

        The conditional UPDATE is the linchpin of breach detection: two
        concurrent requests presenting the same secret race on this statement,
        and exactly one wins. A plain read-then-write would let both rotations
        succeed and a replayed stolen token go unnoticed.

        Args:
            token_id: The token row to consume.

        Returns:
            ``True`` if this call consumed the token; ``False`` if it was
            already consumed (reuse — the caller must treat it as a breach).
        """
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.id == token_id, RefreshToken.is_used.is_(False))
            .values(is_used=True)
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0) == 1

    async def family_started_at(self, family_id: uuid.UUID) -> datetime | None:
        """Return the issuance instant of a family's first token, or ``None``.

        Used to enforce the absolute session-lifetime ceiling across rotations.
        """
        stmt = select(func.min(RefreshToken.created_at)).where(RefreshToken.family_id == family_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_expired(self, *, before: datetime) -> int:
        """Hard-delete token rows whose expiry predates ``before``.

        Keeps ``auth.refresh_tokens`` from growing unboundedly; invoked by the
        periodic cleanup task with a retention grace so recently expired rows
        remain available for incident forensics.

        Args:
            before: Delete rows with ``expires_at`` strictly earlier than this.

        Returns:
            The number of rows deleted.
        """
        stmt = delete(RefreshToken).where(RefreshToken.expires_at < before)
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)

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


class VerificationCodeRepository:
    """The short-lived codes behind email confirmation and password reset."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        code_hash: str,
        expires_at: datetime,
    ) -> VerificationCode:
        """Insert one live code.

        Args:
            user_id: The account the code belongs to.
            purpose: What it proves.
            code_hash: SHA-256 of the code — never the code.
            expires_at: When it stops being redeemable.

        Returns:
            The pending row.
        """
        row = VerificationCode(
            user_id=user_id,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_live(self, *, user_id: uuid.UUID, purpose: str) -> VerificationCode | None:
        """Return this account's redeemable code for a purpose, if any.

        Scoped by ``purpose`` so a confirmation code can never be presented to
        the reset flow: it is simply not found there.

        Args:
            user_id: The account presenting a code.
            purpose: What the code must have been issued for.

        Returns:
            The newest live row, or ``None``.
        """
        stmt = (
            select(VerificationCode)
            .where(
                VerificationCode.user_id == user_id,
                VerificationCode.purpose == purpose,
                VerificationCode.consumed_at.is_(None),
                VerificationCode.expires_at > func.now(),
            )
            .order_by(VerificationCode.id.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def consume_live_codes(self, *, user_id: uuid.UUID, purpose: str) -> int:
        """Kill every live code for this account and purpose.

        Called before issuing a new one. Two live codes double an attacker's
        chances per guess, and an unchecked request endpoint would let them
        accumulate a pool — which is how a million-candidate space becomes a
        small one.

        Args:
            user_id: The account.
            purpose: The purpose whose codes are superseded.

        Returns:
            How many rows were killed.
        """
        stmt = (
            update(VerificationCode)
            .where(
                VerificationCode.user_id == user_id,
                VerificationCode.purpose == purpose,
                VerificationCode.consumed_at.is_(None),
            )
            .values(consumed_at=func.now())
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0)

    async def consume(self, row: VerificationCode) -> None:
        """Mark one code used.

        Kept rather than deleted, so "this code was already redeemed" stays
        answerable — a replay is worth being able to see.

        Args:
            row: The code being spent.
        """
        row.consumed_at = datetime.now(UTC)
        await self._session.flush()

    async def record_attempt(self, row: VerificationCode) -> int:
        """Count one wrong guess against a code.

        Args:
            row: The code that was guessed at.

        Returns:
            The new attempt count.
        """
        row.attempts += 1
        await self._session.flush()
        return row.attempts
