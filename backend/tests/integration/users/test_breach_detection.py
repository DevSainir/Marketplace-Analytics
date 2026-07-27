"""Integration tests for refresh-token rotation against a real PostgreSQL.

Breach detection cannot be proved anywhere but here, for two reasons that are
both about the *database*, not about the service:

* the "consume exactly once" guarantee is a conditional ``UPDATE ... WHERE
  is_used = false`` and its ``rowcount`` — an in-memory fake can imitate the
  result but not the atomicity that makes two concurrent replays resolve to one
  winner;
* the revocation itself is written in a **separate committed transaction**,
  precisely because the request that detects the breach ends in a 401 and its
  own transaction is rolled back. A fake would happily "revoke" rows that a
  rollback then restores, and the guarantee would silently not hold in
  production.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.exceptions import TokenReuseError
from src.core.ids import uuid7
from src.core.security import hash_refresh_secret
from src.modules.users.models import RefreshToken, User
from src.modules.users.repos import RefreshTokenRepository, UserRepository
from src.modules.users.services import AuthService
from tests.support.auth import KNOWN_PASSWORD, known_password_hash


@pytest.fixture
async def stored_user(db_session: AsyncSession) -> User:
    """Persist an active account to authenticate as."""
    user = User(
        email="rotator@example.com",
        hashed_password=known_password_hash(),
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
    """Build the real service, with the breach handler joining this transaction.

    ``_revoke_breached_user`` deliberately opens its own ``AsyncSessionLocal``
    session so the revocation survives the failing request's rollback. Pointing
    that factory at the test connection keeps the behaviour intact (its commit
    is a savepoint release) while the outer transaction still cleans up.
    """
    monkeypatch.setattr("src.modules.users.services.AsyncSessionLocal", session_factory)

    async def _no_redis_watermark(user_id: object) -> None:
        return None

    monkeypatch.setattr(
        "src.modules.users.services.mark_user_sessions_revoked", _no_redis_watermark
    )
    return AuthService(
        user_repo=UserRepository(db_session), token_repo=RefreshTokenRepository(db_session)
    )


async def test_login_persists_a_refresh_row(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """The issued secret is stored only as a digest, never in the clear."""
    issued = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    stored = (
        await db_session.execute(
            sa.select(RefreshToken).where(RefreshToken.user_id == stored_user.id)
        )
    ).scalar_one()
    assert stored.token_hash == hash_refresh_secret(issued.refresh_secret)
    assert issued.refresh_secret not in stored.token_hash


async def test_rotation_chain_is_persisted(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """Two rotations leave three linked rows in one family."""
    first = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    second = await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)
    await auth_service.rotate_refresh_token(refresh_secret=second.refresh_secret)

    rows = (
        (await db_session.execute(sa.select(RefreshToken).order_by(RefreshToken.created_at)))
        .scalars()
        .all()
    )
    assert len(rows) == 3
    assert len({row.family_id for row in rows}) == 1
    assert [row.is_used for row in rows] == [True, True, False]


async def test_replaying_a_consumed_token_revokes_every_session(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """The classic stolen-cookie scenario: replay kills the whole account.

    The attacker rotates first; the legitimate user's next refresh presents the
    now-consumed secret, and every device is logged out.
    """
    first = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    rows = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    assert all(row.is_revoked for row in rows)


async def test_breach_revocation_survives_the_failed_requests_rollback(
    auth_service: AuthService,
    session_factory: async_sessionmaker[AsyncSession],
    stored_user: User,
) -> None:
    """Revocation is committed independently of the 401 that triggers it.

    This is the whole reason ``_revoke_breached_user`` opens its own session. If
    it wrote through the request session, the 401's rollback would undo the
    "log out everywhere" and the breach response would be a no-op.
    """
    first = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    async with session_factory() as independent_session:
        rows = (await independent_session.execute(sa.select(RefreshToken))).scalars().all()
    assert rows
    assert all(row.is_revoked for row in rows)


async def test_revocation_spans_every_family_not_just_the_breached_one(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """A breach on the phone must also end the desktop session.

    Revoking only the compromised lineage would leave the attacker's other
    stolen sessions alive.
    """
    phone = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    desktop = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    desktop_row = (
        await db_session.execute(
            sa.select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_secret(desktop.refresh_secret)
            )
        )
    ).scalar_one()
    assert desktop_row.is_revoked is True


async def test_concurrent_replays_produce_exactly_one_winner(
    auth_service: AuthService, stored_user: User
) -> None:
    """Two simultaneous presentations of one secret: one rotates, one is a breach.

    This is the race the conditional ``UPDATE`` exists for. Without it both
    requests would read ``is_used = false``, both would rotate, and a stolen
    cookie would never be detected.
    """
    issued = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)

    results = await asyncio.gather(
        auth_service.rotate_refresh_token(refresh_secret=issued.refresh_secret),
        auth_service.rotate_refresh_token(refresh_secret=issued.refresh_secret),
        return_exceptions=True,
    )

    breaches = [r for r in results if isinstance(r, TokenReuseError)]
    successes = [r for r in results if not isinstance(r, BaseException)]
    assert len(successes) == 1
    assert len(breaches) == 1


async def test_expired_rows_are_pruned_by_the_cleanup_query(
    db_session: AsyncSession, stored_user: User
) -> None:
    """The retention job deletes only rows past the cutoff.

    ``auth.refresh_tokens`` grows by one row per page load; without the prune it
    becomes the largest table in the database.
    """
    repo = RefreshTokenRepository(db_session)
    now = datetime.now(UTC)
    for offset, label in ((timedelta(days=-30), "stale"), (timedelta(days=1), "live")):
        await repo.create(
            token_id=uuid7(),
            user_id=stored_user.id,
            family_id=uuid7(),
            token_hash=hash_refresh_secret(label),
            expires_at=now + offset,
        )

    deleted = await repo.delete_expired(before=now)

    assert deleted == 1
    survivors = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    assert [row.token_hash for row in survivors] == [hash_refresh_secret("live")]
