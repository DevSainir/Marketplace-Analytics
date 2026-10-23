"""Unit tests for registration: email canonicalization and conflicts.

Signup is open — the shared gate code was removed — so what is left to pin is
the part that decides **whether two signups are the same account**. Getting the
canonical form wrong is not cosmetic: a user who typed mixed case at signup
could never log in again, and case-variant duplicates would register freely.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, ValidationError
from src.modules.users.schemas import PasswordResetConfirmRequest, UserRegisterRequest
from src.modules.users.services import RegistrationService
from tests.support.auth import make_user
from tests.support.fakes import (
    FakePasswordBreachCheck,
    FakeUserRepository,
)


def _service(
    user_repo: FakeUserRepository,
    breach_check: FakePasswordBreachCheck | None = None,
) -> RegistrationService:
    """Build the registration service over in-memory collaborators.

    Creating an account moved out of `AuthService` when that module reached the
    500-line ceiling: sessions and account creation are different jobs that
    happen to share a router.
    """
    return RegistrationService(
        user_repo=user_repo,
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

    outcome = await service.register(email="  User@Example.COM  ", password="a-long-password")

    assert outcome.account.email == "user@example.com"
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

    outcome = await service.register(email="new@example.com", password=password)

    stored = await repo.get_by_id(outcome.account.id)
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

    assert "breaches" in excinfo.value.message


async def test_a_password_not_in_the_corpus_registers_normally() -> None:
    """The check must not become a second, silent way for signup to fail."""
    service = _service(FakeUserRepository([]), breach_check=FakePasswordBreachCheck())

    outcome = await service.register(email="new@example.com", password="a-long-fresh-password")

    assert outcome.account.email == "new@example.com"


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


@pytest.mark.parametrize(
    "password",
    ["alllowercase", "ALLUPPERCASE", "ωμέγααλφάβητο", "ΩΜΕΓΑΑΛΦΑΒΗΤΟ"],
    ids=["latin-lower", "latin-upper", "greek-lower", "greek-upper"],
)
def test_both_password_doors_apply_the_same_case_rule(password: str) -> None:
    """Registration and password reset share one validator.

    Pinned at the schema rather than through two endpoints because the point
    being protected is that there is ONE rule, not two that happen to agree
    today. This module's own comment puts it best: a rule enforced on one of
    two doors is not enforced.
    """
    # Arrange / Act / Assert
    for schema, field in (
        (UserRegisterRequest, "password"),
        (PasswordResetConfirmRequest, "new_password"),
    ):
        payload = {"email": "a@example.com", field: password}
        if schema is PasswordResetConfirmRequest:
            payload["code"] = "123456"
        with pytest.raises(PydanticValidationError):
            schema(**payload)


def test_a_password_with_both_cases_satisfies_both_doors() -> None:
    """The mirror: a rule that refuses everything would pass the test above."""
    # Arrange / Act / Assert
    assert UserRegisterRequest(email="a@example.com", password="ΣωστόςΚωδικός")
    assert PasswordResetConfirmRequest(
        email="a@example.com", code="123456", new_password="ΣωστόςΚωδικός"
    )


async def test_registering_an_unconfirmed_address_resumes_it_instead_of_refusing() -> None:
    """An unfinished signup is the same person coming back, not a clash.

    Answering 409 here was a dead end: the account blocking them was their own,
    created by the attempt they abandoned, and nothing on the screen said so.
    """
    # Arrange
    existing = make_user(email="half@example.com", email_confirmed=False)
    service = _service(FakeUserRepository([existing]))

    # Act
    outcome = await service.register(email="half@example.com", password="A-different-password")

    # Assert — resumed, not created, and answering with the same account.
    assert outcome.created is False
    assert outcome.account.email == "half@example.com"


async def test_a_resumed_signup_leaves_the_stored_password_alone() -> None:
    """The new password goes to the CODE, not to the account.

    This is the account-takeover fix, seen from the registration side. Writing
    the password here would mean an attacker registering after the victim owns
    the credentials the victim then confirms; the digest travels on the
    confirmation code instead and is applied by whoever redeems it.
    """
    # Arrange
    existing = make_user(email="half@example.com", email_confirmed=False)
    before = existing.hashed_password
    service = _service(FakeUserRepository([existing]))

    # Act
    outcome = await service.register(email="half@example.com", password="A-different-password")

    # Assert — the account is untouched, and the candidate is handed back for
    # the caller to bind to the code it is about to mail.
    assert existing.hashed_password == before
    assert outcome.password_hash != before
    assert outcome.password_hash.startswith("$2b$")


async def test_a_confirmed_address_is_still_a_conflict() -> None:
    """The gate above must not swallow the real duplicate case."""
    # Arrange
    service = _service(FakeUserRepository([make_user(email="taken@example.com")]))

    # Act / Assert
    with pytest.raises(ConflictError):
        await service.register(email="taken@example.com", password="A-good-password")
