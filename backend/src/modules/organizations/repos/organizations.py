"""Data access for organisations and their memberships.

Repositories are the only code in this module permitted to build and execute
SQLAlchemy statements; services depend on these classes and never touch the
:class:`AsyncSession` query API directly.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import MemberRole, Membership, Organization


class OrganizationRepository:
    """CRUD operations for :class:`Organization` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        """Return an organisation by primary key, or ``None`` if absent."""
        return await self._session.get(Organization, organization_id)

    async def get_primary(self) -> Organization | None:
        """Return OUR organisation — the one that unlocks internal surfaces.

        At most one row can carry the flag (a partial unique index enforces it),
        so this is a lookup, not a search.
        """
        stmt = select(Organization).where(Organization.is_primary.is_(True))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Organization]:
        """Return every organisation, oldest first (UUIDv7 ids are time-ordered).

        For the dev surface only: no tenant ever sees another tenant's row.
        """
        stmt = select(Organization).order_by(Organization.id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, *, name: str | None, is_primary: bool = False) -> Organization:
        """Insert and flush a new organisation.

        Args:
            name: Display name, or ``None`` to leave it unset (the activation
                service fills it with the owner's email).
            is_primary: Whether this is OUR organisation. Never set from a
                request — only a migration or a dev tool passes ``True``.

        Returns:
            The persisted :class:`Organization` with its generated id populated.
        """
        organization = Organization(name=name, is_primary=is_primary)
        self._session.add(organization)
        await self._session.flush()
        return organization

    async def rename(self, organization: Organization, *, name: str) -> Organization:
        """Set an organisation's display name and flush."""
        organization.name = name
        await self._session.flush()
        return organization


class MembershipRepository:
    """CRUD operations for :class:`Membership` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_for_user(self, user_id: uuid.UUID) -> Membership | None:
        """Return the caller's membership, or ``None`` when they have none.

        ``None`` is the ordinary state of a freshly registered account, not an
        error: it is what the ``user`` role *is*. Every request resolves the
        caller's tenancy through this one lookup, which is only unambiguous
        because ``user_id`` is UNIQUE.
        """
        stmt = select(Membership).where(Membership.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Membership]:
        """Return every member of one organisation, owner first then by join date."""
        stmt = (
            select(Membership)
            .where(Membership.organization_id == organization_id)
            # The owner is the row the member list is *about* — who to contact,
            # who can act — so it leads regardless of who joined when.
            .order_by((Membership.role != MemberRole.OWNER.value), Membership.joined_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_managers(self, organization_id: uuid.UUID) -> int:
        """Count an organisation's managers (the owner is never included).

        The quota this feeds counts seats bought, and an organisation cannot
        exist without its owner, so the owner is not one of them.
        """
        stmt = (
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role == MemberRole.MANAGER.value,
            )
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        role: MemberRole,
        invited_by_user_id: uuid.UUID | None = None,
    ) -> Membership:
        """Insert and flush a new membership.

        Args:
            organization_id: The organisation being joined.
            user_id: The joining account.
            role: ``owner`` (activation) or ``manager`` (invitation).
            invited_by_user_id: The owner who invited them, where there was one.

        Returns:
            The persisted :class:`Membership`.
        """
        membership = Membership(
            organization_id=organization_id,
            user_id=user_id,
            role=role.value,
            invited_by_user_id=invited_by_user_id,
        )
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def delete(self, membership: Membership) -> None:
        """Remove a membership, returning that account to the ``user`` role."""
        await self._session.delete(membership)
        await self._session.flush()
