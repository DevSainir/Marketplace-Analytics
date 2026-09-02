"""Issuing, accepting and revoking manager invitations.

An owner is the only person who can widen access to their own company, and this
is the only way they can do it. What is pinned here is the security of that
door: a forwarded invitation, a revoked one, and one belonging to another
organisation.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from src.modules.organizations.models import MemberRole
from src.modules.organizations.repos import (
    MembershipRepository,
    OrganizationRepository,
)
from tests.integration.organizations.conftest import (
    invitation_service,
    persist_organization,
    persist_user,
)

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Invitations
# --------------------------------------------------------------------------- #
async def test_accepting_an_invitation_joins_as_a_manager(db_session: AsyncSession) -> None:
    """The second door: an owner widens access to their own company."""
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )

    joined = await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    membership = await MembershipRepository(db_session).get_for_user(joiner.id)
    assert joined == org.id
    assert membership is not None
    assert membership.role == MemberRole.MANAGER.value
    # The audit trail survives the invitation row being cleaned up later.
    assert membership.invited_by_user_id == owner.id


async def test_a_targeted_invitation_is_refused_to_a_different_account(
    db_session: AsyncSession,
) -> None:
    """A forwarded invitation does not work for whoever received it.

    This is the assertion that keeps "I invited my accountant" from becoming
    "somebody in my accountant's inbox has our settlement reports".
    """
    owner = await persist_user(db_session, "owner@example.com")
    intended = await persist_user(db_session, "intended@example.com")
    stranger = await persist_user(db_session, "stranger@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id,
        owner_user_id=owner.id,
        email=intended.email,
        valid_for_days=7,
    )

    with pytest.raises(PermissionDeniedError):
        await service.accept(token=invitation.token, user_id=stranger.id, email=stranger.email)

    assert await MembershipRepository(db_session).get_for_user(stranger.id) is None


async def test_a_targeted_invitation_matches_regardless_of_email_case(
    db_session: AsyncSession,
) -> None:
    """«Anna@Example.com» invited, «anna@example.com» registered — same person.

    Emails are normalised on both sides; without that, an owner who typed a
    capital letter would be told their own invitation is not theirs.
    """
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "anna@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id,
        owner_user_id=owner.id,
        email="Anna@Example.COM",
        valid_for_days=7,
    )

    joined = await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    assert joined == org.id


async def test_a_revoked_invitation_stops_working(db_session: AsyncSession) -> None:
    """Revoking is what makes a leaked link recoverable."""
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )

    await service.revoke(organization_id=org.id, invitation_id=invitation.id)

    with pytest.raises(PermissionDeniedError):
        await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)


async def test_an_invitation_cannot_be_revoked_from_another_organisation(
    db_session: AsyncSession,
) -> None:
    """Another company's invitation id is a 404, not a 403.

    A 403 would confirm the id is real, which is exactly what an attacker
    enumerating ids is looking for.
    """
    owner = await persist_user(db_session, "owner@example.com")
    outsider = await persist_user(db_session, "outsider@example.com")
    org = await persist_organization(db_session, owner)
    other_org = await OrganizationRepository(db_session).create(name="ООО Чужая")
    await MembershipRepository(db_session).create(
        organization_id=other_org.id, user_id=outsider.id, role=MemberRole.OWNER
    )
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )

    with pytest.raises(NotFoundError):
        await service.revoke(organization_id=other_org.id, invitation_id=invitation.id)


async def test_an_accepted_invitation_cannot_be_revoked(db_session: AsyncSession) -> None:
    """Revoking an accepted invitation would not remove the membership.

    Reporting success while access stays open is the failure mode this refuses:
    the owner is told to remove the member, which is the action that works.
    """
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )
    await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    with pytest.raises(ConflictError):
        await service.revoke(organization_id=org.id, invitation_id=invitation.id)


async def test_a_pending_invitation_is_offered_to_its_recipient(
    db_session: AsyncSession,
) -> None:
    """«Вас пригласили» — an existing account never needs the link at all."""
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    await service.invite(
        organization_id=org.id,
        owner_user_id=owner.id,
        email=joiner.email,
        valid_for_days=7,
    )

    pending = await service.list_pending_for(email=joiner.email)

    assert len(pending) == 1
    # The organisation's name, and nothing else about it: the caller has not
    # joined yet and is not entitled to its roster or its workspaces.
    assert pending[0].organization_name == "ООО Ромашка"


async def test_a_link_only_invitation_is_offered_to_nobody(db_session: AsyncSession) -> None:
    """A bare link has no recipient, so it appears on no one's profile page."""
    owner = await persist_user(db_session, "owner@example.com")
    other = await persist_user(db_session, "other@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )

    assert await service.list_pending_for(email=other.email) == []


async def test_two_accounts_racing_one_invitation_admit_exactly_one(
    engine: AsyncEngine,
) -> None:
    """Single use is decided in the database, not by a read-then-write.

    An invitation link is a single-use credential and is *made to be forwarded* —
    an owner pastes it into a group chat, two colleagues open it in the same
    second. Every sequential test above passes even against a check-then-write,
    because the first acceptance has committed by the time the second looks.
    This one runs both acceptances on their OWN connections, concurrently, so
    they genuinely interleave the way two requests do.

    Getting it wrong admits two managers on one invitation, over a quota that
    exists to be enforced — and the register claimed this race was covered when
    only the activation-code half of it was.

    Deliberately does NOT use ``db_session``: that fixture wraps everything in
    one rolled-back transaction whose ``commit`` is a savepoint release, so
    nothing it writes is visible to another connection and the race cannot
    happen at all. This commits for real and cleans up after itself.
    """
    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            owner = await persist_user(setup, "race-inv-owner@example.com")
            organization = await persist_organization(setup, owner)
            first = await persist_user(setup, "race-inv-first@example.com")
            second = await persist_user(setup, "race-inv-second@example.com")
            issued = await invitation_service(setup).invite(
                organization_id=organization.id,
                owner_user_id=owner.id,
                email=None,  # a link-only invitation: the forwardable kind
                valid_for_days=7,
            )
            organization_id = organization.id
            first_id, second_id = first.id, second.id
            first_email, second_email = first.email, second.email
            await setup.commit()

        async def _accept(user_id: uuid.UUID, email: str) -> str:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    await invitation_service(session).accept(
                        token=issued.token, user_id=user_id, email=email
                    )
                    await session.commit()
                except (
                    PermissionDeniedError,
                    ConflictError,
                    NotFoundError,
                    IntegrityError,
                    DBAPIError,
                ):
                    await session.rollback()
                    return "refused"
                return "joined"

        outcomes = await asyncio.gather(
            _accept(first_id, first_email), _accept(second_id, second_email)
        )

        async with AsyncSession(engine) as check:
            members = await check.scalar(
                sa.text(
                    "SELECT count(*) FROM organizations.memberships "
                    "WHERE organization_id = :org AND role = 'manager'"
                ),
                {"org": organization_id},
            )

        assert outcomes.count("joined") == 1, outcomes
        assert members == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(sa.text("DELETE FROM auth.users WHERE email LIKE 'race-inv-%'"))
            await cleanup.execute(
                sa.text("DELETE FROM organizations.organizations WHERE name = 'ООО Ромашка'")
            )
            await cleanup.commit()
