"""What the two doors produce: the access every guard is built on.

``resolve_access`` combines the platform role, the membership and the
subscription. These pin the combinations that decide a request — including the
ones that must deny.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ValidationError,
)
from src.modules.organizations.models import MemberRole
from src.modules.organizations.repos import (
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.services.access import EffectiveRole, resolve_access
from src.modules.users.models import ROLE_DEV
from tests.integration.organizations.conftest import (
    invitation_service,
    persist_organization,
    persist_user,
)

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# What the doors produce: the resolved access
# --------------------------------------------------------------------------- #
async def test_a_fresh_account_resolves_to_the_powerless_user_role(
    db_session: AsyncSession,
) -> None:
    """Registration is open, so this is the state an open form creates.

    It must reach nothing: no organisation, and ``can_write`` false. Every data
    router in the application is guarded on exactly this.
    """
    fresh = await persist_user(db_session, "fresh@example.com")

    access = await resolve_access(db_session, user_id=fresh.id, platform_role=fresh.role)

    assert access.role is EffectiveRole.USER
    assert access.organization_id is None
    assert access.can_write is False
    assert access.can_issue_codes is False


async def test_a_dev_outranks_their_membership_role(db_session: AsyncSession) -> None:
    """A dev who owns a company is still a dev.

    The two role sources exist precisely so this state is representable — it is
    the one our own accounts are in.
    """
    dev = await persist_user(db_session, "dev@example.com", role=ROLE_DEV)
    org = await OrganizationRepository(db_session).create(name="Ours")
    await MembershipRepository(db_session).create(
        organization_id=org.id, user_id=dev.id, role=MemberRole.MANAGER
    )

    access = await resolve_access(db_session, user_id=dev.id, platform_role=dev.role)

    assert access.role is EffectiveRole.DEV
    assert access.organization_id == org.id
    assert access.can_issue_codes is True


async def test_the_owner_of_the_primary_organisation_may_issue_codes(
    db_session: AsyncSession,
) -> None:
    """The primary flag is read off the organisation row, and its owner sells accounts."""
    owner = await persist_user(db_session, "owner@example.com")
    org = await OrganizationRepository(db_session).create(name="Ours", is_primary=True)
    await MembershipRepository(db_session).create(
        organization_id=org.id, user_id=owner.id, role=MemberRole.OWNER
    )

    access = await resolve_access(db_session, user_id=owner.id, platform_role=owner.role)

    assert access.role is EffectiveRole.OWNER
    assert access.can_issue_codes is True


async def test_a_customers_owner_may_not_issue_codes(
    db_session: AsyncSession,
) -> None:
    """The same role in a different organisation would be minting free accounts."""
    owner = await persist_user(db_session, "owner@example.com")
    org = await OrganizationRepository(db_session).create(name="Daisy LLC")
    await MembershipRepository(db_session).create(
        organization_id=org.id, user_id=owner.id, role=MemberRole.OWNER
    )

    access = await resolve_access(db_session, user_id=owner.id, platform_role=owner.role)

    assert access.role is EffectiveRole.OWNER
    assert access.can_issue_codes is False


async def test_a_tenant_with_no_subscription_row_reaches_nothing(
    db_session: AsyncSession,
) -> None:
    """Fail closed on a row that should exist and does not.

    Activation writes it in the same transaction as the organisation, so this
    should be unreachable — which is exactly why it is worth pinning that the
    unreachable case denies rather than permits. Since 2026-09-09 that denial
    is the whole service, not just its writes.
    """
    owner = await persist_user(db_session, "owner@example.com")
    org = await OrganizationRepository(db_session).create(name="No Subscription LLC")
    await MembershipRepository(db_session).create(
        organization_id=org.id, user_id=owner.id, role=MemberRole.OWNER
    )

    access = await resolve_access(db_session, user_id=owner.id, platform_role=owner.role)

    assert access.role is EffectiveRole.OWNER
    assert access.has_access is False
    assert access.can_write is False


async def test_a_manager_quota_refuses_a_further_invitation(db_session: AsyncSession) -> None:
    """The quota counts members, not outstanding invitations."""
    owner = await persist_user(db_session, "owner@example.com")
    existing = await persist_user(db_session, "manager@example.com")
    org = await persist_organization(db_session, owner)
    now = datetime.now(UTC)
    await SubscriptionRepository(db_session).create(
        organization_id=org.id,
        started_at=now,
        expires_at=now + timedelta(days=30),
        grace_days=3,
        max_managers=1,
    )
    await MembershipRepository(db_session).create(
        organization_id=org.id, user_id=existing.id, role=MemberRole.MANAGER
    )

    with pytest.raises(ValidationError, match="Manager limit"):
        await invitation_service(db_session).invite(
            organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
        )


async def test_the_owner_is_not_counted_against_the_manager_quota(
    db_session: AsyncSession,
) -> None:
    """An organisation cannot exist without its owner, so the seat is not sold."""
    owner = await persist_user(db_session, "owner@example.com")
    org = await persist_organization(db_session, owner)
    now = datetime.now(UTC)
    await SubscriptionRepository(db_session).create(
        organization_id=org.id,
        started_at=now,
        expires_at=now + timedelta(days=30),
        grace_days=3,
        max_managers=1,
    )

    invitation = await invitation_service(db_session).invite(
        organization_id=org.id, owner_user_id=owner.id, email=None, valid_for_hours=24
    )

    assert invitation.token
    assert isinstance(invitation.id, uuid.UUID)
