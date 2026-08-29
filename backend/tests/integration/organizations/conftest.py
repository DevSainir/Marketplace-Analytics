"""Shared builders for the organisations integration tests.

The three test modules here all need the same three things — an account, and a
service wired to the test session — so they live once rather than three times.
Split by responsibility per the 500-line rule: activation, invitations, and the
access those two produce.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import MemberRole, Organization
from src.modules.organizations.repos import (
    ActivationCodeRepository,
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.services.activation import ActivationService
from src.modules.organizations.services.invitations import InvitationService
from src.modules.users.models import ROLE_USER, User
from tests.support.auth import make_user


async def persist_user(session: AsyncSession, email: str, *, role: str = ROLE_USER) -> User:
    """Persist an account to act as."""
    user = make_user(email=email, role=role)
    session.add(user)
    await session.flush()
    return user


def activation_service(session: AsyncSession) -> ActivationService:
    """Build the activation service against the test session."""
    return ActivationService(
        code_repo=ActivationCodeRepository(session),
        organization_repo=OrganizationRepository(session),
        membership_repo=MembershipRepository(session),
        subscription_repo=SubscriptionRepository(session),
    )


def invitation_service(session: AsyncSession) -> InvitationService:
    """Build the invitation service against the test session."""
    return InvitationService(
        invitation_repo=InvitationRepository(session),
        membership_repo=MembershipRepository(session),
        organization_repo=OrganizationRepository(session),
        subscription_repo=SubscriptionRepository(session),
    )


async def persist_organization(session: AsyncSession, owner: User) -> Organization:
    """An organisation with ``owner`` at its head."""
    org = await OrganizationRepository(session).create(name="ООО Ромашка")
    await MembershipRepository(session).create(
        organization_id=org.id, user_id=owner.id, role=MemberRole.OWNER
    )
    return org
