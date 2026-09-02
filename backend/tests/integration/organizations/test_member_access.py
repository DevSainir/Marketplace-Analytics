"""What an owner grants a manager, and what the guards do with it.

Three properties, and only the whole stack shows any of them: a grant chosen on
the invite form survives acceptance, a manager narrowed afterwards loses the
module immediately, and an owner cannot reach into another company's membership
by guessing a user id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.organizations.models import AccessLevel, ModuleKey
from src.modules.organizations.repos import (
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.schemas import MemberAccessFields
from src.modules.organizations.services.access import (
    EffectiveRole,
    SubscriptionState,
    resolve_access,
)
from src.modules.organizations.services.membership import OrganizationService
from tests.integration.organizations.conftest import (
    invitation_service,
    persist_organization,
    persist_user,
)

pytestmark = pytest.mark.integration


async def _with_live_subscription(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Give the organisation a term that has not lapsed.

    Without one the subscription ramp reports ``read_only``, which would refuse
    the write for a completely different reason and let a test claiming to
    isolate the manager's own level pass while proving nothing.
    """
    now = datetime.now(UTC)
    await SubscriptionRepository(session).create(
        organization_id=organization_id,
        started_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        grace_days=3,
    )


def _service(session: AsyncSession) -> OrganizationService:
    return OrganizationService(
        session=session,
        organization_repo=OrganizationRepository(session),
        membership_repo=MembershipRepository(session),
        subscription_repo=SubscriptionRepository(session),
    )


async def test_the_grant_on_the_invitation_is_what_the_manager_joins_with(
    db_session: AsyncSession,
) -> None:
    """Chosen on the invite form, applied at acceptance — with no window between."""
    # Arrange
    owner = await persist_user(db_session, "owner-a@example.com")
    joiner = await persist_user(db_session, "manager-a@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)

    # Act
    invitation = await service.invite(
        organization_id=org.id,
        owner_user_id=owner.id,
        email=None,
        valid_for_days=7,
        access=MemberAccessFields(
            access_level=AccessLevel.READ_ONLY, modules=[ModuleKey.MONITORING]
        ),
    )
    await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    # Assert
    membership = await MembershipRepository(db_session).get_for_user(joiner.id)
    assert membership is not None
    assert membership.access_level == AccessLevel.READ_ONLY.value
    assert membership.modules == [ModuleKey.MONITORING.value]


async def test_an_invitation_with_no_grant_still_gives_everything(
    db_session: AsyncSession,
) -> None:
    """The default is what a manager got before grants existed."""
    # Arrange
    owner = await persist_user(db_session, "owner-b@example.com")
    joiner = await persist_user(db_session, "manager-b@example.com")
    org = await persist_organization(db_session, owner)
    service = invitation_service(db_session)

    # Act
    invitation = await service.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )
    await service.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    # Assert
    membership = await MembershipRepository(db_session).get_for_user(joiner.id)
    assert membership is not None
    assert membership.access_level == AccessLevel.READ_WRITE.value
    assert sorted(membership.modules) == sorted(m.value for m in ModuleKey)


async def test_narrowing_a_manager_takes_effect_on_their_next_request(
    db_session: AsyncSession,
) -> None:
    """resolve_access is what every guard reads, so this is the whole effect."""
    # Arrange
    owner = await persist_user(db_session, "owner-c@example.com")
    joiner = await persist_user(db_session, "manager-c@example.com")
    org = await persist_organization(db_session, owner)
    await _with_live_subscription(db_session, org.id)
    invites = invitation_service(db_session)
    invitation = await invites.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )
    await invites.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    # Act
    await _service(db_session).set_member_access(
        organization_id=org.id,
        user_id=joiner.id,
        access_level=AccessLevel.READ_ONLY,
        modules=[ModuleKey.MONITORING],
    )

    # Assert
    access = await resolve_access(db_session, user_id=joiner.id, platform_role="user")
    assert access.role is EffectiveRole.MANAGER
    assert access.can_reach(ModuleKey.MONITORING)
    assert not access.can_reach(ModuleKey.FINREPORTS)
    assert not access.can_reach(ModuleKey.AB_TESTS)
    # Read-only bites even though the subscription is healthy: the two reasons
    # a write is refused are independent, and this is the manager one.
    assert access.subscription is not SubscriptionState.READ_ONLY
    assert not access.can_write


async def test_the_owners_own_access_cannot_be_changed(db_session: AsyncSession) -> None:
    """There is no read-only owner; refusing beats pretending to store one."""
    # Arrange
    owner = await persist_user(db_session, "owner-d@example.com")
    org = await persist_organization(db_session, owner)

    # Act / Assert
    with pytest.raises(ValidationError):
        await _service(db_session).set_member_access(
            organization_id=org.id,
            user_id=owner.id,
            access_level=AccessLevel.READ_ONLY,
            modules=[ModuleKey.MONITORING],
        )


async def test_an_owner_cannot_narrow_a_manager_in_another_company(
    db_session: AsyncSession,
) -> None:
    """The lookup is by the (organisation, user) PAIR, which is what stops this."""
    # Arrange — two companies, and the manager belongs to the second.
    owner_one = await persist_user(db_session, "owner-e@example.com")
    org_one = await persist_organization(db_session, owner_one)
    owner_two = await persist_user(db_session, "owner-f@example.com")
    org_two = await persist_organization(db_session, owner_two)
    outsider = await persist_user(db_session, "manager-f@example.com")
    invites = invitation_service(db_session)
    invitation = await invites.invite(
        organization_id=org_two.id, owner_user_id=owner_two.id, email=None, valid_for_days=7
    )
    await invites.accept(token=invitation.token, user_id=outsider.id, email=outsider.email)

    # Act / Assert — the first owner names a real user id that is not theirs.
    with pytest.raises(NotFoundError):
        await _service(db_session).set_member_access(
            organization_id=org_one.id,
            user_id=outsider.id,
            access_level=AccessLevel.READ_ONLY,
            modules=[],
        )

    # And nothing changed on the row they reached for.
    membership = await MembershipRepository(db_session).get_for_user(outsider.id)
    assert membership is not None
    assert membership.access_level == AccessLevel.READ_WRITE.value


async def test_a_manager_with_no_modules_reaches_nothing_but_is_still_a_member(
    db_session: AsyncSession,
) -> None:
    """The empty grant is representable, and means what it says."""
    # Arrange
    owner = await persist_user(db_session, "owner-g@example.com")
    joiner = await persist_user(db_session, "manager-g@example.com")
    org = await persist_organization(db_session, owner)
    await _with_live_subscription(db_session, org.id)
    invites = invitation_service(db_session)
    invitation = await invites.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )
    await invites.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)

    # Act
    await _service(db_session).set_member_access(
        organization_id=org.id,
        user_id=joiner.id,
        access_level=AccessLevel.READ_WRITE,
        modules=[],
    )

    # Assert
    access = await resolve_access(db_session, user_id=joiner.id, platform_role="user")
    assert access.organization_id == org.id
    assert not any(access.can_reach(m) for m in ModuleKey)
    # Still a writer where they can reach — which is nowhere. The two axes do
    # not collapse into each other.
    assert access.can_write


async def test_a_dev_is_never_narrowed_by_a_grant(db_session: AsyncSession) -> None:
    """Our own access must not depend on a customer's membership row."""
    # Arrange
    owner = await persist_user(db_session, "owner-h@example.com")
    joiner = await persist_user(db_session, "dev-h@example.com")
    org = await persist_organization(db_session, owner)
    invites = invitation_service(db_session)
    invitation = await invites.invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_days=7
    )
    await invites.accept(token=invitation.token, user_id=joiner.id, email=joiner.email)
    await _service(db_session).set_member_access(
        organization_id=org.id,
        user_id=joiner.id,
        access_level=AccessLevel.READ_ONLY,
        modules=[],
    )

    # Act — the same row, read for an account whose PLATFORM role is dev.
    access = await resolve_access(db_session, user_id=joiner.id, platform_role="dev")

    # Assert
    assert access.role is EffectiveRole.DEV
    assert all(access.can_reach(m) for m in ModuleKey)
    assert access.can_write


async def test_an_unknown_member_is_a_404_not_a_silent_no_op(db_session: AsyncSession) -> None:
    """A grant that appeared to save and did not is worse than a refusal."""
    # Arrange
    owner = await persist_user(db_session, "owner-i@example.com")
    org = await persist_organization(db_session, owner)

    # Act / Assert
    with pytest.raises(NotFoundError):
        await _service(db_session).set_member_access(
            organization_id=org.id,
            user_id=uuid.uuid4(),
            access_level=AccessLevel.READ_ONLY,
            modules=[ModuleKey.MONITORING],
        )
