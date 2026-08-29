"""Ending every session of one account must actually stop it acting.

Register P1.1. The machinery existed and was unreachable: ``revoke_all_for_user``
and ``mark_user_sessions_revoked`` both worked, and neither had a caller outside
the test suite. So the per-user watermark that ``get_current_user_id`` consults
on every request could never be set, and incident response had no lever at all —
a stolen session simply ran until its tokens expired.

Here rather than lower down because the property is only real against a live
Redis: the watermark is what makes revocation immediate, and a fake would agree
with either answer. Revoking the refresh rows alone is the half that looks like
a fix and is not, since it leaves the access tokens already handed out valid for
up to their full lifetime — exactly the window an incident cannot afford.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthenticationError
from src.core.redis import sessions_revoked_after
from src.core.security import TokenType, decode_token
from src.modules.users.models import RefreshToken, User
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.services import AuthService
from tests.support.auth import KNOWN_PASSWORD, known_password_hash


@pytest.fixture
async def stored_user(db_session: AsyncSession) -> User:
    """Persist an active account to authenticate as."""
    user = User(
        email="compromised@example.com",
        hashed_password=known_password_hash(),
        is_active=True,
        role="user",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def auth_service(db_session: AsyncSession) -> AuthService:
    """Build the real service over the test connection."""
    return AuthService(
        user_repo=UserRepository(db_session),
        token_repo=RefreshTokenRepository(db_session),
    )


async def test_every_device_loses_its_refresh_token(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """Three logins are three families, and all of them end.

    Family scope is right for a logout and for a breach; it is wrong here. This
    is the operation that means "the account itself is not to be trusted".
    """
    for _ in range(3):
        await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    revoked = await auth_service.revoke_all_sessions(user_id=stored_user.id)

    rows = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    assert revoked == 3
    assert all(row.is_revoked for row in rows)


async def test_a_revoked_session_cannot_rotate_a_new_pair(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """The refresh cookie a thief already holds stops working."""
    issued = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    await auth_service.revoke_all_sessions(user_id=stored_user.id)

    with pytest.raises(AuthenticationError):
        await auth_service.rotate_refresh_token(refresh_secret=issued.refresh_secret)


async def test_the_watermark_is_stamped_so_access_tokens_die_immediately(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """The half that makes this an incident lever rather than a slow sign-out.

    Without the watermark the access tokens already issued stay valid for their
    full 15 minutes, which is the window the whole operation exists to close.
    ``get_current_user_id`` rejects any token issued before this instant.
    """
    issued = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    await auth_service.revoke_all_sessions(user_id=stored_user.id)

    watermark = await sessions_revoked_after(stored_user.id)
    assert watermark is not None
    payload = decode_token(issued.access_token, expected_type=TokenType.ACCESS)
    assert payload is not None
    assert payload.issued_at < watermark


async def test_it_is_scoped_to_the_named_account(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """One compromised account must not sign the rest of the platform out.

    The blast radius is the reason ``logout`` and breach detection refuse to
    stamp the watermark at all; this one may, and must still stop at the account.
    """
    other = User(
        email="bystander@example.com",
        hashed_password=known_password_hash(),
        is_active=True,
        role="user",
    )
    db_session.add(other)
    await db_session.flush()
    theirs = await auth_service.authenticate(email=other.email, password=KNOWN_PASSWORD)
    await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    await auth_service.revoke_all_sessions(user_id=stored_user.id)

    assert await sessions_revoked_after(other.id) is None
    rotated = await auth_service.rotate_refresh_token(refresh_secret=theirs.refresh_secret)
    assert rotated.access_token


async def test_revoking_an_account_with_no_sessions_is_not_an_error(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """Zero is an answer, not a failure.

    Incident response runs this against accounts that may already be dormant,
    and an error there would read as "the lever did not work".
    """
    revoked = await auth_service.revoke_all_sessions(user_id=stored_user.id)

    assert revoked == 0


async def test_a_second_revocation_is_idempotent(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """Running it twice is safe; the second finds nothing left to revoke."""
    await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    first = await auth_service.revoke_all_sessions(user_id=stored_user.id)
    second = await auth_service.revoke_all_sessions(user_id=stored_user.id)

    assert first == 1
    assert second == 0
