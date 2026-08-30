"""Unit tests for registration: email canonicalization and conflicts.

Signup is open — the shared gate code was removed — so what is left to pin is
the part that decides **whether two signups are the same account**. Getting the
canonical form wrong is not cosmetic: a user who typed mixed case at signup
could never log in again, and case-variant duplicates would register freely.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, ValidationError
from src.modules.users.services import AuthService
from tests.support.auth import make_user
from tests.support.fakes import (
    FakeLoginBackoff,
    FakePasswordBreachCheck,
    FakeRefreshTokenRepository,
    FakeUserRepository,
)


def _service(
    user_repo: FakeUserRepository,
    breach_check: FakePasswordBreachCheck | None = None,
) -> AuthService:
    """Build an AuthService over in-memory repositories and fake collaborators."""
    return AuthService(
        user_repo=user_repo,
        token_repo=FakeRefreshTokenRepository(),
        backoff=FakeLoginBackoff(),
        breach_check=breach_check or FakePasswordBreachCheck(),
    )


async def test_duplicate_email_is_a_conflict() -> None:
    """Re-registering an existing email fails instead of creating a twin."""
    repo = FakeUserRepository([make_user(email="taken@example.com")])
    service = _service(repo)

    with pytest.raises(ConflictError):
        await service.register(email="taken@example.com", password="a-long-password")


async def test_email_case_and_padding_are_canonicalized() -> None:
    """``  User@Example.COM `` and ``user@example.com`` are one account.

    Without canonicalization a user who typed mixed case at signup could never
    log in again, and case-variant duplicates would register freely.
    """
    repo = FakeUserRepository()
    service = _service(repo)

    created = await service.register(email="  User@Example.COM  ", password="a-long-password")

    assert created.email == "user@example.com"
    assert await repo.get_by_email("user@example.com") is not None


async def test_case_variant_of_an_existing_email_is_a_conflict() -> None:
    """The duplicate check runs on the canonical form, not the raw input."""
    repo = FakeUserRepository([make_user(email="taken@example.com")])
    service = _service(repo)

    with pytest.raises(ConflictError):
        await service.register(email="TAKEN@Example.com", password="a-long-password")


async def test_password_is_never_stored_in_plaintext() -> None:
    """Persistence receives a bcrypt digest, never the password itself."""
    repo = FakeUserRepository()
    service = _service(repo)
    password = "a-long-password"

    created = await service.register(email="new@example.com", password=password)

    stored = await repo.get_by_id(created.id)
    assert stored is not None
    assert stored.hashed_password != password
    assert stored.hashed_password.startswith("$2b$")


async def test_lost_insert_race_becomes_a_conflict_not_a_500() -> None:
    """Two simultaneous signups for one email: the loser gets 409, not 500.

    Both requests pass the pre-check, and the unique index catches the second
    at INSERT time. Letting that ``IntegrityError`` escape would surface as a
    server error on an ordinary user mistake.
    """

    class _RacingRepo(FakeUserRepository):
        async def create(self, *, email: str, hashed_password: str):  # type: ignore[no-untyped-def]
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    service = _service(_RacingRepo())

    with pytest.raises(ConflictError):
        await service.register(email="racer@example.com", password="a-long-password")


async def test_a_password_from_a_public_breach_is_refused() -> None:
    """Length was the only rule; "Password1!" passes it and leads every stuffing list."""
    breach_check = FakePasswordBreachCheck(breached={"Password1!"})
    service = _service(FakeUserRepository([]), breach_check=breach_check)

    with pytest.raises(ValidationError) as excinfo:
        await service.register(email="new@example.com", password="Password1!")

    assert "утечках" in excinfo.value.message


async def test_a_password_not_in_the_corpus_registers_normally() -> None:
    """The check must not become a second, silent way for signup to fail."""
    service = _service(FakeUserRepository([]), breach_check=FakePasswordBreachCheck())

    user = await service.register(email="new@example.com", password="a-long-fresh-password")

    assert user.email == "new@example.com"


async def test_a_taken_email_is_refused_before_the_password_is_checked() -> None:
    """No point asking a third party about a signup that cannot succeed anyway."""
    breach_check = FakePasswordBreachCheck(breached={"Password1!"})
    service = _service(
        FakeUserRepository([make_user(email="taken@example.com")]),
        breach_check=breach_check,
    )

    with pytest.raises(ConflictError):
        await service.register(email="taken@example.com", password="Password1!")

    assert breach_check.asked == []
