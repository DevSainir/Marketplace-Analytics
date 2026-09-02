"""Data access for activation codes and invitations.

Both are looked up by the SHA-256 of a secret the caller presents, never by a
plaintext value — the digest is what the column stores, so hashing happens in
the service and the repository only ever sees the digest.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import ActivationCode, Invitation, MemberRole


class ActivationCodeRepository:
    """CRUD operations for :class:`ActivationCode` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_hash(self, code_hash: str) -> ActivationCode | None:
        """Return the code with this digest, or ``None`` if unknown."""
        stmt = select(ActivationCode).where(ActivationCode.code_hash == code_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ActivationCode]:
        """Return every code, newest first (dev surface only)."""
        stmt = select(ActivationCode).order_by(ActivationCode.id.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        code_hash: str,
        note: str,
        subscription_days: int,
        expires_at: datetime | None,
        created_by_user_id: uuid.UUID | None,
    ) -> ActivationCode:
        """Insert and flush a newly generated code."""
        code = ActivationCode(
            code_hash=code_hash,
            note=note,
            subscription_days=subscription_days,
            expires_at=expires_at,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(code)
        await self._session.flush()
        return code

    async def claim(
        self, code_id: uuid.UUID, *, used_at: datetime, used_by_user_id: uuid.UUID
    ) -> bool:
        """Atomically consume a code, exactly once across concurrent callers.

        A conditional UPDATE, for the same reason
        :meth:`~src.modules.users.repos.RefreshTokenRepository.consume` is one:
        a read-then-write lets two requests both observe ``used_at IS NULL`` and
        both proceed. For a refresh token that hides a breach; here it means one
        code sold once creates TWO paid organisations, and nothing afterwards
        can tell which was the legitimate one.

        The caller must claim BEFORE building anything, so a lost race creates
        no organisation at all.

        Args:
            code_id: The code row to consume.
            used_at: Redemption instant.
            used_by_user_id: The redeeming account.

        Returns:
            ``True`` if this call consumed the code; ``False`` if another
            request already had — which the caller must treat exactly like an
            invalid code.
        """
        stmt = (
            update(ActivationCode)
            .where(ActivationCode.id == code_id, ActivationCode.used_at.is_(None))
            .values(used_at=used_at, used_by_user_id=used_by_user_id)
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0) == 1

    async def attach_organization(self, code_id: uuid.UUID, *, organization_id: uuid.UUID) -> None:
        """Record which organisation a claimed code created.

        Separate from :meth:`claim` because the organisation does not exist yet
        when the code is claimed — and claiming first is what makes the race
        safe. Kept rather than deleted afterwards: this is the only link between
        a payment taken offline and the organisation it produced.
        """
        stmt = (
            update(ActivationCode)
            .where(ActivationCode.id == code_id)
            .values(organization_id=organization_id)
        )
        await self._session.execute(stmt)


class InvitationRepository:
    """CRUD operations for :class:`Invitation` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_hash(self, token_hash: str) -> Invitation | None:
        """Return the invitation with this token digest, or ``None`` if unknown."""
        stmt = select(Invitation).where(Invitation.token_hash == token_hash)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, invitation_id: uuid.UUID) -> Invitation | None:
        """Return an invitation by primary key, or ``None`` if absent."""
        return await self._session.get(Invitation, invitation_id)

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Invitation]:
        """Return every invitation an organisation has issued, newest first.

        Accepted and revoked ones included: the owner's list is a history of who
        was let in and by whom, not just a queue of what is outstanding.
        """
        stmt = (
            select(Invitation)
            .where(Invitation.organization_id == organization_id)
            .order_by(Invitation.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_for_email(self, email: str) -> list[Invitation]:
        """Return the live invitations addressed to one email address.

        This is what puts «Вас пригласили» on a registered user's own profile
        page without them ever seeing a link. Revoked and accepted rows are
        filtered out here; expiry is judged by the service against its own
        clock, so that "expired" reads the same everywhere.
        """
        stmt = (
            select(Invitation)
            .where(
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .order_by(Invitation.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        email: str | None,
        token_hash: str,
        role: MemberRole,
        created_by_user_id: uuid.UUID,
        expires_at: datetime,
        access_level: str,
        modules: list[str],
    ) -> Invitation:
        """Insert and flush a new invitation.

        Args:
            organization_id: The organisation being joined.
            email: Address it is addressed to, or ``None`` for a bare link.
            token_hash: SHA-256 of the link token.
            role: The membership granted (``manager`` today).
            created_by_user_id: The owner issuing it.
            expires_at: When it stops being acceptable.

        Returns:
            The persisted :class:`Invitation`.
        """
        invitation = Invitation(
            organization_id=organization_id,
            email=email,
            token_hash=token_hash,
            role=role.value,
            created_by_user_id=created_by_user_id,
            expires_at=expires_at,
            access_level=access_level,
            modules=modules,
        )
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def claim(
        self,
        invitation_id: uuid.UUID,
        *,
        accepted_at: datetime,
        accepted_by_user_id: uuid.UUID,
    ) -> bool:
        """Atomically accept an invitation, exactly once.

        Conditional UPDATE for the same reason as
        :meth:`ActivationCodeRepository.claim`: a link forwarded to two people
        who open it in the same second would otherwise admit both. It also
        re-checks ``revoked_at`` inside the statement, so an owner revoking
        while someone is accepting resolves one way or the other rather than
        both.

        Returns:
            ``True`` if this call consumed the invitation; ``False`` if it was
            already accepted or revoked.
        """
        stmt = (
            update(Invitation)
            .where(
                Invitation.id == invitation_id,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .values(accepted_at=accepted_at, accepted_by_user_id=accepted_by_user_id)
        )
        result = cast("CursorResult[Any]", await self._session.execute(stmt))
        return int(result.rowcount or 0) == 1

    async def mark_revoked(self, invitation: Invitation, *, revoked_at: datetime) -> Invitation:
        """Withdraw an outstanding invitation, leaving the row as a record."""
        invitation.revoked_at = revoked_at
        await self._session.flush()
        return invitation
