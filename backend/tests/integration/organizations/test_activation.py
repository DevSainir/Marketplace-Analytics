"""Redeeming an activation code — the door that creates an organisation.

Persistence-heavy in ways a fake cannot stand in for: single use is enforced by a
stored timestamp claimed with a conditional UPDATE, and redemption writes four
rows that must all land or none. The security cases get their own tests — a
wrong code, a replayed code, an expired one — because each is a way in if it is
not closed.
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
    PermissionDeniedError,
)
from src.core.security import hash_opaque_secret
from src.modules.organizations.models import MemberRole, Organization
from src.modules.organizations.repos import (
    ActivationCodeRepository,
    MembershipRepository,
    SubscriptionRepository,
)
from src.modules.users.models import ROLE_DEV
from tests.integration.organizations.conftest import (
    activation_service,
    persist_user,
)
from tests.support.auth import make_user

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
async def test_redeeming_a_code_makes_the_caller_an_owner_with_a_subscription(
    db_session: AsyncSession,
) -> None:
    """The one path that creates an organisation, end to end.

    Asserts all four rows the redemption is supposed to write, because a
    partial success here is the worst outcome available: an organisation with
    no owner is unreachable by anyone, and its code is already spent.
    """
    dev = await persist_user(db_session, "dev@example.com", role=ROLE_DEV)
    buyer = await persist_user(db_session, "buyer@example.com")
    service = activation_service(db_session)
    issued = await service.generate_code(
        note="ООО Ромашка, 15000₽",
        valid_for_days=30,
        subscription_days=30,
        created_by_user_id=dev.id,
    )

    organization = await service.redeem(code=issued.code, user_id=buyer.id, email=buyer.email)

    membership = await MembershipRepository(db_session).get_for_user(buyer.id)
    subscription = await SubscriptionRepository(db_session).get_for_organization(organization.id)
    assert membership is not None
    assert membership.role == MemberRole.OWNER.value
    assert membership.organization_id == organization.id
    assert subscription is not None
    # 30 days, give or take the seconds this test took to run.
    assert (subscription.expires_at - subscription.started_at).days == 30
    # The organisation is named after its owner, so nothing had to be typed.
    assert organization.name == buyer.email
    assert organization.is_primary is False


async def test_a_code_cannot_be_redeemed_twice(db_session: AsyncSession) -> None:
    """Single use, and the second attempt is indistinguishable from a wrong code.

    Without this, one code sold once buys an unlimited number of organisations —
    it would be passed around, and we would have no way to know.
    """
    dev = await persist_user(db_session, "dev@example.com", role=ROLE_DEV)
    first = await persist_user(db_session, "first@example.com")
    second = await persist_user(db_session, "second@example.com")
    service = activation_service(db_session)
    issued = await service.generate_code(
        note="", valid_for_days=30, subscription_days=30, created_by_user_id=dev.id
    )
    await service.redeem(code=issued.code, user_id=first.id, email=first.email)

    with pytest.raises(PermissionDeniedError):
        await service.redeem(code=issued.code, user_id=second.id, email=second.email)

    assert await MembershipRepository(db_session).get_for_user(second.id) is None


async def test_an_unknown_code_is_refused(db_session: AsyncSession) -> None:
    """A guessed code creates nothing, and says only that it is invalid."""
    buyer = await persist_user(db_session, "buyer@example.com")

    with pytest.raises(PermissionDeniedError):
        await activation_service(db_session).redeem(
            code="definitely-not-a-real-code", user_id=buyer.id, email=buyer.email
        )


async def test_an_expired_code_is_refused(db_session: AsyncSession) -> None:
    """A code handed out and never used stops working.

    An unbounded code is a standing grant of a paid account sitting in
    somebody's chat history.
    """
    dev = await persist_user(db_session, "dev@example.com", role=ROLE_DEV)
    buyer = await persist_user(db_session, "buyer@example.com")
    service = activation_service(db_session)
    issued = await service.generate_code(
        note="", valid_for_days=1, subscription_days=30, created_by_user_id=dev.id
    )
    row = await ActivationCodeRepository(db_session).get_by_hash(hash_opaque_secret(issued.code))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    with pytest.raises(PermissionDeniedError):
        await service.redeem(code=issued.code, user_id=buyer.id, email=buyer.email)


async def test_a_second_organisation_is_refused_for_an_existing_member(
    db_session: AsyncSession,
) -> None:
    """One organisation per user — the model's central simplification."""
    dev = await persist_user(db_session, "dev@example.com", role=ROLE_DEV)
    buyer = await persist_user(db_session, "buyer@example.com")
    service = activation_service(db_session)
    first = await service.generate_code(
        note="", valid_for_days=30, subscription_days=30, created_by_user_id=dev.id
    )
    second = await service.generate_code(
        note="", valid_for_days=30, subscription_days=30, created_by_user_id=dev.id
    )
    await service.redeem(code=first.code, user_id=buyer.id, email=buyer.email)

    with pytest.raises(ConflictError):
        await service.redeem(code=second.code, user_id=buyer.id, email=buyer.email)


# --------------------------------------------------------------------------- #
# Concurrency: single use has to hold under a race, not just in sequence
# --------------------------------------------------------------------------- #
async def test_two_accounts_racing_one_code_produce_exactly_one_organisation(
    engine: AsyncEngine,
) -> None:
    """Single use is decided in the database, not by a read-then-write.

    The sequential test above passes even with a check-then-write, because the
    first redemption has committed by the time the second looks. This one runs
    both redemptions on their OWN connections, concurrently, so they genuinely
    interleave — which is what a production request pair does.

    Getting this wrong means one code sold once creates two paid organisations,
    and nothing afterwards can say which was legitimate.

    Deliberately does NOT use ``db_session``: that fixture wraps everything in
    one transaction that is rolled back, and its ``commit`` is a savepoint
    release — so nothing it writes is ever visible to another connection, and
    the race could not happen at all. This test therefore commits for real and
    cleans up after itself.
    """
    dev = make_user(email="race-dev@example.com", role=ROLE_DEV)
    first = make_user(email="race-first@example.com")
    second = make_user(email="race-second@example.com")

    try:
        async with AsyncSession(engine, expire_on_commit=False) as setup:
            setup.add_all([dev, first, second])
            await setup.flush()
            issued = await activation_service(setup).generate_code(
                note="", valid_for_days=30, subscription_days=30, created_by_user_id=dev.id
            )
            await setup.commit()

        async def _redeem(user_id: uuid.UUID, email: str) -> str:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                try:
                    await activation_service(session).redeem(
                        code=issued.code, user_id=user_id, email=email
                    )
                    await session.commit()
                except (PermissionDeniedError, ConflictError, IntegrityError, DBAPIError):
                    await session.rollback()
                    return "refused"
                return "redeemed"

        outcomes = await asyncio.gather(
            _redeem(first.id, first.email), _redeem(second.id, second.email)
        )

        async with AsyncSession(engine) as check:
            organisations = list((await check.execute(sa.select(Organization.id))).scalars().all())

        assert outcomes.count("redeemed") == 1, outcomes
        assert len(organisations) == 1
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(sa.text("DELETE FROM organizations.organizations"))
            await cleanup.execute(sa.text("DELETE FROM auth.users WHERE email LIKE 'race-%'"))
            await cleanup.commit()
