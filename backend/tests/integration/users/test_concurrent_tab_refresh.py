"""Three tabs refreshing at once must not look like a stolen cookie.

Register item P0.5. Tabs share one cookie jar, so on page load each fires
``/refresh`` with the **same** secret. The first rotates it; the rest present a
token that is now consumed, which rotation could not tell from a replayed stolen
one — so it revoked the family and signed the user out. That is a false positive
on every multi-tab user, and a control that produces those is one that ends up
switched off.

Here rather than in the unit tier because the property under test is about the
database rows the rotation leaves behind — which token is live, which family is
intact — and about the real Redis the grace window lives in. A fake could agree
with either answer.

The complementary half — a replay *outside* the window still kills the lineage —
is ``test_breach_detection.py``, which runs with the window disabled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import settings
from src.core.exceptions import TokenReuseError
from src.core.security import TokenType, decode_token, hash_refresh_secret
from src.modules.users.models import RefreshToken, User
from src.modules.users.refresh_grace import recall_rotation
from src.modules.users.services import AuthService
from tests.support.auth import KNOWN_PASSWORD, known_password_hash


@pytest.fixture(autouse=True)
def _fernet_key(settings_override: Any) -> Iterator[None]:
    """Give the grace store a key to encrypt the child secret with.

    It is the only thing in the app that holds a usable refresh secret at rest,
    so it encrypts — and failing to encrypt degrades the store rather than the
    refresh, which means without a key these tests would silently exercise the
    behaviour they exist to prove is gone. CI runs this tier with the key empty
    (the tenancy tests generate their own the same way), so it has to be set
    here rather than assumed.
    """
    with settings_override(fernet_secret_key=Fernet.generate_key().decode()):
        yield


@pytest.fixture
async def stored_user(db_session: AsyncSession) -> User:
    """Persist an active account to authenticate as."""
    user = User(
        email="tabs@example.com",
        hashed_password=known_password_hash(),
        # Confirmed: `/login` refuses an unproven address, so an account a
        # test authenticates as has to be one.
        email_confirmed_at=datetime.now(UTC),
        is_active=True,
        role="user",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def auth_service(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> AuthService:
    """Build the real service with the breach handler on the test connection."""
    monkeypatch.setattr("src.modules.users.services.breach.AsyncSessionLocal", session_factory)
    from src.modules.users.repos import RefreshTokenRepository, UserRepository

    return AuthService(
        user_repo=UserRepository(db_session),
        token_repo=RefreshTokenRepository(db_session),
    )


async def test_a_second_tab_is_served_the_rotation_the_first_one_got(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """The racing tab gets a working session, not a 401.

    This is the whole bug: the second tab's cookie was identical to the first's,
    and presenting it signed the user out of everything.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    first_tab = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    second_tab = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    assert second_tab.refresh_secret == first_tab.refresh_secret


async def test_the_family_survives_the_race(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """No row is revoked, so every other device stays signed in.

    The 2026-07-27 outage was this: one benign replay ending sessions that were
    being actively worked in.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    rows = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    assert not any(row.is_revoked for row in rows)


async def test_every_tab_converges_on_one_live_token(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """Grace re-serves the same child; it does not let the family branch.

    Issuing each racing tab its own sibling would be easier and would quietly
    destroy the property rotation exists for: with several live leaves, a stolen
    token can be rotated alongside the real one indefinitely and never be
    detected. Exactly one unused row is the assertion that rules that out.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    for _ in range(3):
        await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    rows = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    assert len([row for row in rows if not row.is_used]) == 1
    assert len(rows) == 2


async def test_the_re_served_tab_gets_a_full_length_access_token(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """The refresh secret is shared; the access token is minted for this request.

    Only the refresh secret is stored and re-served. The access token is created
    fresh against the child's id, so the later tab gets a full lifetime rather
    than the remainder of the first tab's — which is what caching the whole
    bundle would have handed it.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    first_tab = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    second_tab = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)

    second = decode_token(second_tab.access_token, expected_type=TokenType.ACCESS)
    first = decode_token(first_tab.access_token, expected_type=TokenType.ACCESS)
    assert second is not None
    assert first is not None
    assert second.jti == first.jti
    remaining = second_tab.access_expires_at - datetime.now(UTC)
    assert remaining > timedelta(seconds=settings.access_token_ttl_seconds - 60)


async def test_the_grace_entry_holds_no_readable_secret(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """The one place a usable refresh secret rests is encrypted.

    Redis persists to an AOF volume that backups include, so a plaintext secret
    here would be a credential at rest in every backup.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    issued = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)
    parent = (
        await db_session.execute(
            sa.select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_secret(login.refresh_secret)
            )
        )
    ).scalar_one()

    stored = await redis_client.get(f"auth:refresh-grace:{parent.id}")  # type: ignore[attr-defined]

    assert stored is not None
    assert issued.refresh_secret not in str(stored)
    assert await recall_rotation(parent_id=parent.id) == issued.refresh_secret


async def test_a_replay_of_a_token_whose_child_was_revoked_is_still_a_breach(
    auth_service: AuthService,
    db_session: AsyncSession,
    stored_user: User,
    redis_client: object,
) -> None:
    """A live grace entry is not a licence to resurrect a dead session.

    Logout revokes the family but leaves the grace entry's TTL running. Serving
    it blindly would let a consumed cookie be traded for a working session after
    the user had signed out.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    issued = await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)
    await auth_service.logout(refresh_secret=issued.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret)


async def test_two_simultaneous_refreshes_both_succeed(
    auth_service: AuthService, stored_user: User, redis_client: object
) -> None:
    """The race the bug is named for, run as an actual race.

    Sequential calls prove the grace lookup; firing both at once also exercises
    the conditional consume underneath it, which is what decides there is one
    winner to be served in the first place.
    """
    login = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    results = await asyncio.gather(
        auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret),
        auth_service.rotate_refresh_token(refresh_secret=login.refresh_secret),
        return_exceptions=True,
    )

    assert not any(isinstance(result, BaseException) for result in results)
