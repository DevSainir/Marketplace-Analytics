"""Changing a password from inside a session.

Three rules, and each is the reason the route exists in this shape:

* the CURRENT password is required — without it a live session is enough to
  lock the owner out of their own account;
* the other sessions end, because a password change is what somebody does when
  they think a credential got out;
* this one does not, because signing out whoever just proved themselves twice
  is a puzzle rather than a control.

The mailed-code path is a different thing and is tested next door in
``test_account_recovery.py``: a code proves the mailbox, which is what the
*forgotten*-password flow has nothing else to go on for.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.exceptions import AuthenticationError, ValidationError
from src.core.ids import uuid7
from src.core.security import verify_password
from src.modules.users.services.password_change import PasswordChangeService
from tests.support.auth import KNOWN_PASSWORD, make_user
from tests.support.fakes import (
    FakePasswordBreachCheck,
    FakeRefreshTokenRepository,
    FakeUserRepository,
)

NEW_PASSWORD = "Sovsem-Drugoj-2026"


def _service(
    users: FakeUserRepository,
    tokens: FakeRefreshTokenRepository,
    *,
    breached: set[str] | None = None,
) -> PasswordChangeService:
    """Build the service over in-memory repositories."""
    return PasswordChangeService(
        users=users,
        tokens=tokens,
        breach_check=FakePasswordBreachCheck(breached=breached),
    )


async def _open_session(tokens: FakeRefreshTokenRepository, user_id, family_id) -> None:
    """Give the account one live refresh row on the named lineage."""
    await tokens.create(
        token_id=uuid7(),
        user_id=user_id,
        family_id=family_id,
        token_hash=f"hash-{family_id}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )


@pytest.mark.asyncio
async def test_the_wrong_current_password_changes_nothing() -> None:
    """A live session alone must not be enough to replace the password."""
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    before = user.hashed_password
    service = _service(users, FakeRefreshTokenRepository())

    # Act / Assert
    with pytest.raises(AuthenticationError):
        await service.change(
            user=user,
            current_password="not-the-password",
            new_password=NEW_PASSWORD,
            keep_family_id=uuid7(),
        )
    assert user.hashed_password == before


@pytest.mark.asyncio
async def test_the_new_password_replaces_the_old_one() -> None:
    """The happy path actually writes a digest of the new password."""
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    service = _service(users, FakeRefreshTokenRepository())

    # Act
    await service.change(
        user=user,
        current_password=KNOWN_PASSWORD,
        new_password=NEW_PASSWORD,
        keep_family_id=uuid7(),
    )

    # Assert
    assert verify_password(NEW_PASSWORD, user.hashed_password)
    assert not verify_password(KNOWN_PASSWORD, user.hashed_password)


@pytest.mark.asyncio
async def test_a_password_already_in_a_public_leak_is_refused() -> None:
    """The breach check applies here exactly as it does at registration."""
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    service = _service(users, FakeRefreshTokenRepository(), breached={NEW_PASSWORD})
    before = user.hashed_password

    # Act / Assert
    with pytest.raises(ValidationError):
        await service.change(
            user=user,
            current_password=KNOWN_PASSWORD,
            new_password=NEW_PASSWORD,
            keep_family_id=uuid7(),
        )
    assert user.hashed_password == before


@pytest.mark.asyncio
async def test_reusing_the_same_password_is_refused() -> None:
    """«Сменил» has to mean something — the same string is not a change."""
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    service = _service(users, FakeRefreshTokenRepository())

    # Act / Assert
    with pytest.raises(ValidationError):
        await service.change(
            user=user,
            current_password=KNOWN_PASSWORD,
            new_password=KNOWN_PASSWORD,
            keep_family_id=uuid7(),
        )


@pytest.mark.asyncio
async def test_the_other_sessions_end_and_this_one_survives() -> None:
    """The whole point: the stolen laptop goes, the browser doing it stays."""
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    tokens = FakeRefreshTokenRepository()
    mine, phone, laptop = uuid7(), uuid7(), uuid7()
    for family in (mine, phone, laptop):
        await _open_session(tokens, user.id, family)
    service = _service(users, tokens)

    # Act
    ended = await service.change(
        user=user,
        current_password=KNOWN_PASSWORD,
        new_password=NEW_PASSWORD,
        keep_family_id=mine,
    )

    # Assert
    assert ended == 2
    live = {t.family_id for t in tokens.tokens.values() if not t.is_revoked}
    assert live == {mine}


@pytest.mark.asyncio
async def test_an_unknown_lineage_spares_nothing() -> None:
    """A token predating the `fam` claim cannot say which session is mine.

    So every session ends, this one included. Being wrong in the other
    direction would leave alive whichever session the password was changed
    because of.
    """
    # Arrange
    user = make_user()
    users = FakeUserRepository([user])
    tokens = FakeRefreshTokenRepository()
    for _ in range(2):
        await _open_session(tokens, user.id, uuid7())
    service = _service(users, tokens)

    # Act
    ended = await service.change(
        user=user,
        current_password=KNOWN_PASSWORD,
        new_password=NEW_PASSWORD,
        keep_family_id=None,
    )

    # Assert
    assert ended == 2
    assert all(t.is_revoked for t in tokens.tokens.values())


@pytest.mark.asyncio
async def test_another_accounts_sessions_are_untouched() -> None:
    """One person changing their password must not sign anybody else out."""
    # Arrange
    user = make_user()
    stranger = make_user(email="stranger@example.com")
    users = FakeUserRepository([user, stranger])
    tokens = FakeRefreshTokenRepository()
    theirs = uuid7()
    await _open_session(tokens, user.id, uuid7())
    await _open_session(tokens, stranger.id, theirs)
    service = _service(users, tokens)

    # Act
    await service.change(
        user=user,
        current_password=KNOWN_PASSWORD,
        new_password=NEW_PASSWORD,
        keep_family_id=None,
    )

    # Assert
    survivors = {t.family_id for t in tokens.tokens.values() if not t.is_revoked}
    assert survivors == {theirs}
