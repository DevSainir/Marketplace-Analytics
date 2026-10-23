"""Issuing, accepting and revoking manager invitations.

An owner is the only person who can widen access to their own company, and this
is the only way they can do it. What is pinned here is the security of that
door: a forwarded invitation, a revoked one, and one belonging to another
organisation.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.core.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from src.modules.organizations.models import MemberRole
from src.modules.organizations.repos import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
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
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
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
        valid_for_hours=24,
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
        valid_for_hours=24,
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
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
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
    other_org = await OrganizationRepository(db_session).create(name="Foreign LLC")
    await MembershipRepository(db_session).create(
        organization_id=other_org.id, user_id=outsider.id, role=MemberRole.OWNER
    )
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
    )

    with pytest.raises(NotFoundError):
        await service.revoke(organization_id=other_org.id, invitation_id=invitation.id)


async def test_an_already_used_invitation_can_still_be_revoked(db_session: AsyncSession) -> None:
    """Reversed: a link that got out AND was used is the urgent one to kill.

    This used to refuse, on the reasoning that revoking would not remove the
    membership it created — true then, because one invitation admitted exactly
    one person and revoking it afterwards achieved nothing.

    A reusable link inverts that. Somebody having already come through says
    nothing about how many more can, so refusing to withdraw it would leave the
    door open on the one link an owner has evidence about. Revoking stops the
    LINK; removing a member is the separate act for whoever is already inside.
    """
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    late = await persist_user(db_session, "late@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
    )
    await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    await service.revoke(organization_id=org.id, invitation_id=invitation.id)

    # The door is shut for the next person...
    with pytest.raises(PermissionDeniedError):
        await service.accept(token=invitation.token, user_id=late.id, email=late.email)
    # ...and the one who already joined is still a member, which is why removing
    # them is a separate action.
    assert await MembershipRepository(db_session).get_for_user(joiner.id) is not None


async def test_a_pending_invitation_is_offered_to_its_recipient(
    db_session: AsyncSession,
) -> None:
    """The "You're invited" list — an existing account never needs the link at all."""
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    await service.invite(
        organization_id=org.id,
        owner_user_id=owner.id,
        email=joiner.email,
        valid_for_hours=24,
    )

    pending = await service.list_pending_for(email=joiner.email)

    assert len(pending) == 1
    # The organisation's name, and nothing else about it: the caller has not
    # joined yet and is not entitled to its roster or its workspaces.
    assert pending[0].organization_name == "Daisy LLC"


async def test_a_link_only_invitation_is_offered_to_nobody(db_session: AsyncSession) -> None:
    """A bare link has no recipient, so it appears on no one's profile page."""
    owner = await persist_user(db_session, "owner@example.com")
    other = await persist_user(db_session, "other@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
    )

    assert await service.list_pending_for(email=other.email) == []


async def test_two_accounts_can_join_through_one_forwarded_link(
    engine: AsyncEngine,
) -> None:
    """Reversed: an invitation admits everyone who holds it, until it expires.

    This test used to assert the opposite — that exactly one of two racing
    acceptances succeeded — because an invitation was a single-use credential
    claimed with a conditional UPDATE. Single use is gone deliberately: a link
    is *made to be forwarded*, an owner pastes it into a group chat, and having
    it work for the first colleague and fail for the second was the wrong
    shape. What bounds it now is the window (one hour by default) and the
    manager quota, which is re-checked at acceptance precisely because this can
    happen.

    Kept as a CONCURRENT test rather than a sequential one, because the thing
    worth pinning is that both arrivals are recorded when they genuinely
    interleave — the counter is incremented in SQL, not read-modify-written.

    Deliberately does NOT use ``db_session``: that fixture wraps everything in
    one rolled-back transaction whose ``commit`` is a savepoint release, so
    nothing it writes is visible to another connection. This commits for real
    and cleans up after itself.
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
                valid_for_hours=24,
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
            # Both arrivals counted. A read-modify-write would lose one of two
            # simultaneous increments and under-report a link that got out,
            # which is the number an owner uses to notice exactly that.
            used = await check.scalar(
                sa.text(
                    "SELECT accepted_count FROM organizations.invitations "
                    "WHERE organization_id = :org"
                ),
                {"org": organization_id},
            )

        assert used == 2

        assert outcomes.count("joined") == 2, outcomes
        assert members == 2
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(sa.text("DELETE FROM auth.users WHERE email LIKE 'race-inv-%'"))
            await cleanup.execute(
                sa.text("DELETE FROM organizations.organizations WHERE name = 'Daisy LLC'")
            )
            await cleanup.commit()


async def test_the_manager_quota_is_re_checked_at_acceptance_not_only_at_issue(
    db_session: AsyncSession,
) -> None:
    """One link, one seat left, two arrivals — the second is refused.

    The quota used to be checked only when an invitation was ISSUED, which was
    enough while one invitation admitted one person: counting members at that
    moment bounded what the invitation could add. A reusable link breaks that
    arithmetic — the check becomes historical, and the second, third and fourth
    acceptance walk straight past a limit that was legal when the link was made.

    So it is checked again here, at the moment a seat is actually taken.
    """
    owner = await persist_user(db_session, "owner@example.com")
    first = await persist_user(db_session, "first@example.com")
    second = await persist_user(db_session, "second@example.com")
    org = await persist_organization(db_session, owner)
    now = datetime.now(UTC)
    await SubscriptionRepository(db_session).create(
        organization_id=org.id,
        started_at=now,
        expires_at=now + timedelta(days=30),
        grace_days=3,
        max_managers=1,
    )
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=1
    )

    await service.accept(token=invitation.token, user_id=first.id, email=first.email)

    with pytest.raises(ValidationError):
        await service.accept(token=invitation.token, user_id=second.id, email=second.email)

    assert await MembershipRepository(db_session).get_for_user(second.id) is None


async def test_a_link_keeps_working_for_a_second_person_within_its_window(
    db_session: AsyncSession,
) -> None:
    """The mirror of the quota test: without a cap, the link admits both.

    A refusal test alone would pass against a link that had simply stopped
    working, which is the behaviour being removed.
    """
    owner = await persist_user(db_session, "owner@example.com")
    first = await persist_user(db_session, "first@example.com")
    second = await persist_user(db_session, "second@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=1
    )

    await service.accept(token=invitation.token, user_id=first.id, email=first.email)
    await service.accept(token=invitation.token, user_id=second.id, email=second.email)

    assert await MembershipRepository(db_session).get_for_user(second.id) is not None


async def test_an_expired_link_stops_working(db_session: AsyncSession) -> None:
    """The window is what bounds a reusable link, so it has to actually bite."""
    owner = await persist_user(db_session, "owner@example.com")
    joiner = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=1
    )
    # Reach past the service to age it: there is no way to issue an expired one,
    # and waiting an hour is not a test.
    row = await InvitationRepository(db_session).get_by_id(invitation.id)
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(PermissionDeniedError):
        await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)
