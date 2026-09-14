"""Data-access layer for the Users module.

Repositories are the *only* code permitted to build and execute SQLAlchemy
statements for this module. Services depend on these classes and never touch the
:class:`AsyncSession` query API directly, satisfying the Clean Architecture
boundary "business logic has no direct database access".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class SessionRow:
    """One login lineage, as the session list needs it.

    A plain dataclass rather than a Pydantic model: this is what the repository
    returns, not what the API answers, and keeping the two apart is what lets
    the response DTO decide what a caller may see.
    """

    family_id: uuid.UUID
    #: Verbatim and unparsed — naming the device is the SPA's job.
    user_agent: str | None
    ip_address: str | None
    #: When this lineage's first token was minted: the moment of the login.
    started_at: datetime
    #: When its newest token was minted — the last sign of life, within one
    #: access-token TTL.
    last_seen_at: datetime


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
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> RefreshToken:
        """Persist a newly issued refresh-token row.

        Args:
            token_id: UUIDv7 id (also the JWT ``jti``).
            user_id: Owning user's id.
            family_id: Login-lineage identifier shared across the chain.
            token_hash: SHA-256 digest of the opaque refresh secret.
            expires_at: Absolute expiry (UTC).
            parent_id: Superseded token id, or ``None`` for a fresh login.
            user_agent: The caller's browser string, truncated to the column.
                ``None`` when the caller did not supply one, or when the writer
                has no request to read it from (a test, a confirm-email flow).
            ip_address: The caller's address as ``resolve_client_ip`` gives it.

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
            # Truncate here rather than trusting the sender: a 10 kB header
            # would otherwise fail the INSERT and, with it, the login.
            user_agent=user_agent[:400] if user_agent else None,
            ip_address=ip_address[:45] if ip_address else None,
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

    async def list_sessions(self, user_id: uuid.UUID) -> list[SessionRow]:
        """Return one row per live login lineage of this account.

        A session is a FAMILY, not a token: one login, rotated every fifteen
        minutes for as long as the browser stays open, is one line in the list
        and a hundred-odd rows in this table. So the aggregate is the answer —
        when the lineage began, when it last rotated, and the browser and
        address of its **newest** node, which is where the session is now rather
        than where it started.

        Revoked and expired lineages are left out: this list is what somebody
        looks at to decide whether to end something, and a dead session is not
        a decision. A family with a single revoked row disappears entirely,
        which is what «завершён» should look like.

        Args:
            user_id: The account whose sessions to list.

        Returns:
            Newest-active-first. Empty for an account with nothing open.
        """
        # The newest node per family, by created_at. DISTINCT ON is Postgres's
        # own idiom for it and costs one index scan; a window function or a
        # correlated subquery would say the same thing more slowly.
        newest = (
            select(
                RefreshToken.family_id,
                RefreshToken.user_agent,
                RefreshToken.ip_address,
                RefreshToken.created_at.label("last_seen_at"),
            )
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
                RefreshToken.expires_at > func.now(),
            )
            .distinct(RefreshToken.family_id)
            .order_by(RefreshToken.family_id, RefreshToken.created_at.desc())
            .subquery()
        )
        started = (
            select(
                RefreshToken.family_id,
                func.min(RefreshToken.created_at).label("started_at"),
            )
            .where(RefreshToken.user_id == user_id)
            .group_by(RefreshToken.family_id)
            .subquery()
        )
        stmt = (
            select(
                newest.c.family_id,
                newest.c.user_agent,
                newest.c.ip_address,
                newest.c.last_seen_at,
                started.c.started_at,
            )
            .join(started, started.c.family_id == newest.c.family_id)
            .order_by(newest.c.last_seen_at.desc())
        )
        result = await self._session.execute(stmt)
        return [
            SessionRow(
                family_id=row.family_id,
                user_agent=row.user_agent,
                ip_address=row.ip_address,
                started_at=row.started_at,
                last_seen_at=row.last_seen_at,
            )
            for row in result
        ]

    async def family_belongs_to(self, *, family_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether this account owns that login lineage.

        The ownership check behind "end this session". Answering it in SQL
        rather than by loading the row and comparing is the difference between
        a scoped query and a filtered one — see the `security` skill.
        """
        stmt = select(RefreshToken.id).where(
            RefreshToken.family_id == family_id,
            RefreshToken.user_id == user_id,
        )
        return (await self._session.execute(stmt.limit(1))).first() is not None

    async def live_family_ids(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Every login lineage of this account that is still usable.

        Used to end all the others when a password changes. Reading the list
        first, and revoking family by family, is what lets the caller keep the
        session it is speaking on — the account-wide lever cannot.
        """
        stmt = (
            select(RefreshToken.family_id)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
                RefreshToken.expires_at > func.now(),
            )
            .distinct()
        )
        return list((await self._session.execute(stmt)).scalars().all())

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
        pending_password_hash: str | None = None,
    ) -> VerificationCode:
        """Insert one live code.

        Args:
            user_id: The account the code belongs to.
            purpose: What it proves.
            code_hash: SHA-256 of the code — never the code.
            expires_at: When it stops being redeemable.
            pending_password_hash: bcrypt digest of the password typed in the
                attempt this code belongs to, applied when it is redeemed.

        Returns:
            The pending row.
        """
        row = VerificationCode(
            user_id=user_id,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
            pending_password_hash=pending_password_hash,
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
