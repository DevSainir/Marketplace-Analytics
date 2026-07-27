"""Unit tests for registration: invite gating, email canonicalization, conflicts.

The platform is single-tenant — every account can read the seller's whole
business, so registration is a gate, not a funnel. These tests pin the gate's
behaviour and the email normalization that decides whether two signups are the
same account.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, PermissionDeniedError
from src.modules.users.services import AuthService
from tests.support.auth import make_user
from tests.support.fakes import FakeRefreshTokenRepository, FakeUserRepository

INVITE = "operator-issued-invite"


def _service(user_repo: FakeUserRepository) -> AuthService:
    """Build an AuthService over in-memory repositories."""
    return AuthService(user_repo=user_repo, token_repo=FakeRefreshTokenRepository())


async def test_valid_invite_creates_the_account(settings_override) -> None:
    """A correct invite code registers the user and returns the public DTO."""
    repo = FakeUserRepository()
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE):
        created = await service.register(
            email="new@example.com", password="a-long-password", invite_code=INVITE
        )

    assert created.email == "new@example.com"
    assert created.is_active is True
    assert await repo.get_by_email("new@example.com") is not None


async def test_wrong_invite_code_is_refused(settings_override) -> None:
    """A guessed invite code registers nobody."""
    repo = FakeUserRepository()
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE), pytest.raises(PermissionDeniedError):
        await service.register(
            email="intruder@example.com", password="a-long-password", invite_code="guess"
        )

    assert repo.users == {}


@pytest.mark.parametrize(
    "submitted",
    ["привет", "invite—dash", "café", "🔑"],
    ids=["cyrillic", "em-dash", "accented", "emoji"],
)
async def test_a_non_ascii_invite_code_is_refused_not_crashed(
    settings_override, submitted: str
) -> None:
    """A non-ASCII invite code is a wrong code, never a server error.

    ``secrets.compare_digest`` refuses non-ASCII ``str`` operands with a
    TypeError, so comparing the submitted code as text turned any Cyrillic or
    emoji input into an unauthenticated 500 on ``POST /register``. The gate must
    treat it as exactly what it is: a code that does not match.
    """
    repo = FakeUserRepository()
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE), pytest.raises(PermissionDeniedError):
        await service.register(
            email="intruder@example.com", password="a-long-password", invite_code=submitted
        )

    assert repo.users == {}


async def test_a_non_ascii_invite_code_can_also_be_the_correct_one(settings_override) -> None:
    """An operator who configures a non-ASCII code can still register with it.

    The byte-level comparison is not just crash-proofing: it makes the whole
    Unicode range usable as an invite secret.
    """
    repo = FakeUserRepository()
    service = _service(repo)
    code = "пригласительный-код"

    with settings_override(registration_invite_code=code):
        created = await service.register(
            email="guest@example.com", password="a-long-password", invite_code=code
        )

    assert created.email == "guest@example.com"


async def test_empty_configured_code_disables_registration(settings_override) -> None:
    """An unset ``REGISTRATION_INVITE_CODE`` closes registration entirely.

    Not "accepts any code" and not "accepts an empty code" — an operator who
    never configured the variable must not have an open signup form.
    """
    repo = FakeUserRepository()
    service = _service(repo)

    with settings_override(registration_invite_code=""), pytest.raises(PermissionDeniedError):
        await service.register(email="a@example.com", password="a-long-password", invite_code="")

    assert repo.users == {}


async def test_duplicate_email_is_a_conflict(settings_override) -> None:
    """Re-registering an existing email fails instead of creating a twin."""
    repo = FakeUserRepository([make_user(email="taken@example.com")])
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE), pytest.raises(ConflictError):
        await service.register(
            email="taken@example.com", password="a-long-password", invite_code=INVITE
        )


async def test_email_case_and_padding_are_canonicalized(settings_override) -> None:
    """``  User@Example.COM `` and ``user@example.com`` are one account.

    Without canonicalization a user who typed mixed case at signup could never
    log in again, and case-variant duplicates would register freely.
    """
    repo = FakeUserRepository()
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE):
        created = await service.register(
            email="  User@Example.COM  ", password="a-long-password", invite_code=INVITE
        )

    assert created.email == "user@example.com"
    assert await repo.get_by_email("user@example.com") is not None


async def test_case_variant_of_an_existing_email_is_a_conflict(settings_override) -> None:
    """The duplicate check runs on the canonical form, not the raw input."""
    repo = FakeUserRepository([make_user(email="taken@example.com")])
    service = _service(repo)

    with settings_override(registration_invite_code=INVITE), pytest.raises(ConflictError):
        await service.register(
            email="TAKEN@Example.com", password="a-long-password", invite_code=INVITE
        )


async def test_password_is_never_stored_in_plaintext(settings_override) -> None:
    """Persistence receives a bcrypt digest, never the password itself."""
    repo = FakeUserRepository()
    service = _service(repo)
    password = "a-long-password"

    with settings_override(registration_invite_code=INVITE):
        created = await service.register(
            email="new@example.com", password=password, invite_code=INVITE
        )

    stored = await repo.get_by_id(created.id)
    assert stored is not None
    assert stored.hashed_password != password
    assert stored.hashed_password.startswith("$2b$")


async def test_lost_insert_race_becomes_a_conflict_not_a_500(settings_override) -> None:
    """Two simultaneous signups for one email: the loser gets 409, not 500.

    Both requests pass the pre-check, and the unique index catches the second
    at INSERT time. Letting that ``IntegrityError`` escape would surface as a
    server error on an ordinary user mistake.
    """

    class _RacingRepo(FakeUserRepository):
        async def create(self, *, email: str, hashed_password: str):  # type: ignore[no-untyped-def]
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    service = _service(_RacingRepo())

    with settings_override(registration_invite_code=INVITE), pytest.raises(ConflictError):
        await service.register(
            email="racer@example.com", password="a-long-password", invite_code=INVITE
        )
