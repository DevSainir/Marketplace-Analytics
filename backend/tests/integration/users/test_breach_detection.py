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

Most of the file runs with the **replay grace window disabled** (see the
``_strict_rotation`` fixture). A replay inside that window is now served the
rotation's child instead of ending the family — that is register item P0.5, and
it is covered on its own below. What these tests pin is the behaviour that
matters for theft: a token replayed once the window has passed still kills the
lineage. Disabling grace is how they say "later" without sleeping through it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

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


@pytest.fixture(autouse=True)
def _strict_rotation(settings_override: Any) -> Iterator[None]:
    """Run this file outside the replay grace window.

    Zero is the documented "no grace" setting, so this is the real production
    behaviour for a replay arriving after the window — not a test-only hook. The
    grace path itself is exercised in ``test_concurrent_tab_refresh.py``.
    """
    with settings_override(refresh_replay_grace_seconds=0):
        yield


@pytest.fixture
async def stored_user(db_session: AsyncSession) -> User:
    """Persist an active account to authenticate as."""
    user = User(
        email="rotator@example.com",
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
    redis_client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> AuthService:
    """Build the real service, with the breach handler joining this transaction.

    ``_revoke_breached_family`` deliberately opens its own ``AsyncSessionLocal``
    session so the revocation survives the failing request's rollback. Pointing
    that factory at the test connection keeps the behaviour intact (its commit
    is a savepoint release) while the outer transaction still cleans up.

    Breach handling itself still touches no Redis — stamping the per-user
    revocation watermark was account-wide by construction, which is the blast
    radius these tests pin shut. ``redis_client`` is here for a different
    reason: ``authenticate`` consults the per-account login backoff (P1.5), so
    every ``login`` in this file now reaches the shared client. Without a
    per-test one, the process-wide client hands the second test connections
    bound to the first test's event loop — which surfaces as "attached to a
    different loop", several confusing minutes from its cause.
    """
    monkeypatch.setattr("src.modules.users.services.breach.AsyncSessionLocal", session_factory)
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


async def test_replaying_a_consumed_token_revokes_that_lineage(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """The classic stolen-cookie scenario: replay kills the lineage.

    The attacker rotates first; the legitimate user's next refresh presents the
    now-consumed secret. Both ends of that lineage are cut, so neither party can
    mint another token from it. Here the account has exactly one family, so
    "this lineage" and "everything" coincide — see
    :func:`test_revocation_spares_the_users_other_devices` for the case that
    distinguishes them.
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

    This is the whole reason ``_revoke_breached_family`` opens its own session.
    If it wrote through the request session, the 401's rollback would undo the
    revocation and the breach response would be a silent no-op.
    """
    first = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    async with session_factory() as independent_session:
        rows = (await independent_session.execute(sa.select(RefreshToken))).scalars().all()
    assert rows
    assert all(row.is_revoked for row in rows)


async def test_revocation_spares_the_users_other_devices(
    auth_service: AuthService, db_session: AsyncSession, stored_user: User
) -> None:
    """A replay on the phone must NOT end the desktop session.

    This is the 2026-07-27 outage, pinned. The team shares one login, so that
    account carried a live family per device. A tab last used three days earlier
    woke up and replayed the token it had gone to sleep holding; the old handler
    read that as an account breach and revoked all fourteen families at once,
    signing every worker out mid-task.

    A replay is genuinely ambiguous — a resumed laptop and a thief look
    identical on the wire — so the response is scoped to the lineage that
    actually presented the dead token (RFC 9700 §4.14.2). The replaying device
    still has to log in again; nobody else is touched.

    The inverse of this assertion is what shipped before, so this test is the
    thing standing between the team and a repeat.
    """
    phone = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    desktop = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    rows = (await db_session.execute(sa.select(RefreshToken))).scalars().all()
    desktop_row = next(
        row for row in rows if row.token_hash == hash_refresh_secret(desktop.refresh_secret)
    )
    assert desktop_row.is_revoked is False, "an unrelated device was signed out by the replay"

    # ...and every row of the lineage that DID replay is dead, so this is a
    # narrowing of the response, not a removal of it.
    phone_rows = [row for row in rows if row.family_id != desktop_row.family_id]
    assert len(phone_rows) == 2, "fixture sanity: the phone family is issue + rotation"
    assert all(row.is_revoked for row in phone_rows)


async def test_the_desktop_can_still_rotate_after_the_phone_was_breached(
    auth_service: AuthService, stored_user: User
) -> None:
    """The surviving device keeps working, not merely keeps an unrevoked row.

    Checking ``is_revoked`` alone would still pass if some other guard (the
    Redis watermark, an account flag) locked the account out. What the team
    needs is the desktop's *next* refresh succeeding, which is what actually
    failed for them on 27.07.
    """
    phone = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    desktop = await auth_service.authenticate(email=stored_user.email, password=KNOWN_PASSWORD)
    await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    with pytest.raises(TokenReuseError):
        await auth_service.rotate_refresh_token(refresh_secret=phone.refresh_secret)

    rotated = await auth_service.rotate_refresh_token(refresh_secret=desktop.refresh_secret)
    assert rotated.access_token


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
