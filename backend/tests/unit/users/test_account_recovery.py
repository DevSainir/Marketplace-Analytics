"""Email confirmation and password reset (register P1.6).

The entry's warning is the reason most of these exist: *building this badly is
worse than not having it.* A reset flow is a full authentication path bolted on
somewhere other than the login path, which is exactly how the careful rules the
login path follows get left behind.

So what is pinned here is mostly the rules, not the happy path:

* the endpoints never disclose whether an address is registered;
* a code is single-use, expires, and dies after a capped number of guesses;
* issuing a new code kills the old one, so codes cannot be pooled;
* a code issued for one purpose is not accepted for the other;
* a completed reset ends **every** session, not just the caller's.

The happy paths are here too, but only so the refusals above are not passing
because nothing works at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.core.exceptions import ValidationError
from src.core.security import hash_opaque_secret, verify_password
from src.integrations.email import EmailMessage
from src.modules.users.models import VerificationPurpose
from src.modules.users.services.recovery import AccountRecoveryService
from src.modules.users.services.verification import VerificationService, generate_code
from tests.support.auth import KNOWN_PASSWORD, make_user
from tests.support.fakes import FakePasswordBreachCheck, FakeUserRepository


class FakeCodeRow:
    """A stored verification code, as the repository hands it back."""

    def __init__(self, *, user_id: uuid.UUID, purpose: str, code_hash: str, expires_at: datetime):
        """Start live, unconsumed and unguessed."""
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.purpose = purpose
        self.code_hash = code_hash
        self.expires_at = expires_at
        self.consumed_at: datetime | None = None
        self.attempts = 0


class FakeCodeRepo:
    """In-memory stand-in with the surface the verification service uses."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[FakeCodeRow] = []

    async def create(
        self, *, user_id: uuid.UUID, purpose: str, code_hash: str, expires_at: datetime
    ) -> FakeCodeRow:
        """Store one live code."""
        row = FakeCodeRow(
            user_id=user_id, purpose=purpose, code_hash=code_hash, expires_at=expires_at
        )
        self.rows.append(row)
        return row

    async def get_live(self, *, user_id: uuid.UUID, purpose: str) -> FakeCodeRow | None:
        """Return the newest redeemable row for this account and purpose."""
        now = datetime.now(UTC)
        live = [
            r
            for r in self.rows
            if r.user_id == user_id
            and r.purpose == purpose
            and r.consumed_at is None
            and r.expires_at > now
        ]
        return live[-1] if live else None

    async def consume_live_codes(self, *, user_id: uuid.UUID, purpose: str) -> int:
        """Kill every live row for this account and purpose."""
        killed = 0
        for row in self.rows:
            if row.user_id == user_id and row.purpose == purpose and row.consumed_at is None:
                row.consumed_at = datetime.now(UTC)
                killed += 1
        return killed

    async def consume(self, row: FakeCodeRow) -> None:
        """Mark one row used."""
        row.consumed_at = datetime.now(UTC)

    async def record_attempt(self, row: FakeCodeRow) -> int:
        """Count a wrong guess."""
        row.attempts += 1
        return row.attempts


class FakeTransport:
    """Captures what would have been mailed."""

    def __init__(self, *, fails: bool = False) -> None:
        """Optionally behave like a relay that is down."""
        self.sent: list[EmailMessage] = []
        self.fails = fails

    async def send(self, message: EmailMessage) -> None:
        """Record the message, or raise like a dead relay."""
        if self.fails:
            raise OSError("relay unreachable")
        self.sent.append(message)


def _service(
    users: FakeUserRepository,
    codes: FakeCodeRepo,
    transport: FakeTransport,
    breach_check: FakePasswordBreachCheck | None = None,
) -> AccountRecoveryService:
    """Build the recovery service over in-memory collaborators.

    The breach check is faked even when a test does not care about it: the
    real one is an HTTPS range query, and a unit test that reaches the network
    is slow, offline-fragile, and no longer a unit test.
    """
    return AccountRecoveryService(
        users=users,
        verification=VerificationService(codes=codes),
        transport=transport,
        breach_check=breach_check or FakePasswordBreachCheck(),
    )


def _code_from(transport: FakeTransport) -> str:
    """Pull the six digits out of the message that was sent."""
    body = transport.sent[-1].body
    return next(part for part in body.split() if part.isdigit() and len(part) >= 6)


# --------------------------------------------------------------------------- #
# The code itself
# --------------------------------------------------------------------------- #
def test_a_code_keeps_its_leading_zeros() -> None:
    """`"004271"` is a valid code; trimming it would shrink the keyspace tenfold."""
    codes = {generate_code(6) for _ in range(2000)}

    assert all(len(code) == 6 for code in codes)
    assert all(code.isdigit() for code in codes)


async def test_a_code_is_stored_hashed_and_never_in_the_clear() -> None:
    """A dump, a backup or a stray SELECT * must yield nothing redeemable."""
    repo = FakeCodeRepo()
    user_id = uuid.uuid4()

    code = await VerificationService(codes=repo).issue(
        user_id=user_id, purpose=VerificationPurpose.EMAIL_CONFIRMATION
    )

    assert repo.rows[0].code_hash != code
    assert repo.rows[0].code_hash == hash_opaque_secret(code)


async def test_a_code_works_once() -> None:
    """Single-use: a replay of a spent code is worth nothing."""
    repo = FakeCodeRepo()
    service = VerificationService(codes=repo)
    user_id = uuid.uuid4()
    code = await service.issue(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET)

    first = await service.redeem(
        user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=code
    )
    second = await service.redeem(
        user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=code
    )

    assert first is True
    assert second is False


async def test_issuing_a_new_code_kills_the_previous_one() -> None:
    """Otherwise an attacker pools live codes and the keyspace collapses.

    Six digits is a million candidates. A hundred live codes make it ten
    thousand — which is why the request endpoint may not simply add rows.
    """
    repo = FakeCodeRepo()
    service = VerificationService(codes=repo)
    user_id = uuid.uuid4()
    first = await service.issue(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET)

    await service.issue(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET)

    assert (
        await service.redeem(
            user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=first
        )
        is False
    )


async def test_a_code_dies_after_the_capped_guesses(settings_override: Any) -> None:
    """The cap is what makes six digits acceptable at all.

    The row is CONSUMED at the cap, not merely counted: leaving it alive would
    let an attacker keep working the same target.
    """
    repo = FakeCodeRepo()
    service = VerificationService(codes=repo)
    user_id = uuid.uuid4()

    with settings_override(verification_code_max_attempts=3):
        code = await service.issue(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET)
        for _ in range(3):
            await service.redeem(
                user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code="000000"
            )
        # Even the RIGHT code is now worthless.
        assert (
            await service.redeem(
                user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=code
            )
            is False
        )

    assert repo.rows[0].consumed_at is not None


async def test_an_expired_code_is_refused(settings_override: Any) -> None:
    """Short-lived, so a code read over a shoulder is usually already dead."""
    repo = FakeCodeRepo()
    service = VerificationService(codes=repo)
    user_id = uuid.uuid4()
    code = await service.issue(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET)
    repo.rows[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    assert (
        await service.redeem(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=code)
        is False
    )


async def test_a_confirmation_code_cannot_reset_a_password() -> None:
    """The two purposes are requested under different circumstances.

    One of them changes a credential, so a code obtained for the harmless one
    must not be spendable on the other.
    """
    repo = FakeCodeRepo()
    service = VerificationService(codes=repo)
    user_id = uuid.uuid4()
    code = await service.issue(user_id=user_id, purpose=VerificationPurpose.EMAIL_CONFIRMATION)

    assert (
        await service.redeem(user_id=user_id, purpose=VerificationPurpose.PASSWORD_RESET, code=code)
        is False
    )


# --------------------------------------------------------------------------- #
# Non-disclosure
# --------------------------------------------------------------------------- #
async def test_a_reset_request_for_an_unknown_address_is_silent() -> None:
    """Not an error — a non-event that must look exactly like the event.

    A reset form that answers "no such user" is an account-enumeration endpoint
    reachable without even a password guess.
    """
    transport = FakeTransport()
    service = _service(FakeUserRepository([]), FakeCodeRepo(), transport)

    await service.request_password_reset(email="nobody@example.com")

    assert transport.sent == []


async def test_a_disabled_account_gets_no_reset_mail() -> None:
    """Re-enabling is our decision; a reset must not be a way around it."""
    transport = FakeTransport()
    disabled = make_user(email="fired@example.com", is_active=False)
    service = _service(FakeUserRepository([disabled]), FakeCodeRepo(), transport)

    await service.request_password_reset(email="fired@example.com")

    assert transport.sent == []


async def test_confirming_an_unknown_address_answers_like_a_wrong_code() -> None:
    """Same answer for "no such account" and "wrong code"."""
    service = _service(FakeUserRepository([]), FakeCodeRepo(), FakeTransport())

    assert await service.confirm_email(email="nobody@example.com", code="123456") is False


async def test_resetting_an_unknown_address_answers_like_a_wrong_code() -> None:
    """Same answer again, on the endpoint that actually changes a credential."""
    service = _service(FakeUserRepository([]), FakeCodeRepo(), FakeTransport())

    result = await service.reset_password(
        email="nobody@example.com", code="123456", new_password="a-brand-new-password"
    )

    assert result is None


# --------------------------------------------------------------------------- #
# The flows end to end
# --------------------------------------------------------------------------- #
async def test_a_mailed_code_confirms_the_address() -> None:
    """The happy path, so every refusal above means something."""
    # `email_confirmed=False` explicitly: the factory now hands out CONFIRMED
    # accounts, because that is the only state `/login` accepts and most tests
    # are not about this. A test that confirms an address has to start before it.
    user = make_user(email="user@example.com", email_confirmed=False)
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)
    await service.send_confirmation(user=user)

    confirmed = await service.confirm_email(email="user@example.com", code=_code_from(transport))

    assert confirmed is True
    assert user.email_confirmed_at is not None


async def test_a_confirmed_address_is_not_mailed_again() -> None:
    """Otherwise anyone with a session can spray mail at a settled address."""
    user = make_user(email="user@example.com")
    user.email_confirmed_at = datetime.now(UTC)
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)

    await service.send_confirmation(user=user)

    assert transport.sent == []


async def test_re_confirming_keeps_the_original_timestamp() -> None:
    """During an incident the FIRST answer to "when was this proven" is the one."""
    user = make_user(email="user@example.com", email_confirmed=False)
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)
    await service.send_confirmation(user=user)
    await service.confirm_email(email="user@example.com", code=_code_from(transport))
    first = user.email_confirmed_at

    await service.send_confirmation(user=user)

    assert user.email_confirmed_at == first


async def test_a_reset_changes_the_password() -> None:
    """The happy path for the flow that changes a credential."""
    user = make_user(email="user@example.com")
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)
    await service.request_password_reset(email="user@example.com")

    result = await service.reset_password(
        email="user@example.com",
        code=_code_from(transport),
        new_password="a-brand-new-password",
    )

    assert result is not None
    assert verify_password("a-brand-new-password", user.hashed_password)
    assert not verify_password(KNOWN_PASSWORD, user.hashed_password)


async def test_a_wrong_reset_code_leaves_the_password_alone() -> None:
    """The obvious one, and the one whose absence would be catastrophic."""
    user = make_user(email="user@example.com")
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)
    await service.request_password_reset(email="user@example.com")

    result = await service.reset_password(
        email="user@example.com", code="000000", new_password="attacker-chosen"
    )

    assert result is None
    assert verify_password(KNOWN_PASSWORD, user.hashed_password)


async def test_a_completed_reset_settles_the_address_too() -> None:
    """Proving the mailbox now is at least as good as confirming it earlier."""
    user = make_user(email="user@example.com")
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)
    await service.request_password_reset(email="user@example.com")

    await service.reset_password(
        email="user@example.com",
        code=_code_from(transport),
        new_password="a-brand-new-password",
    )

    assert user.email_confirmed_at is not None


async def test_the_message_carries_the_code_and_says_what_to_do() -> None:
    """An unexpected reset mail is the earliest warning a person gets."""
    user = make_user(email="user@example.com")
    transport = FakeTransport()
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), transport)

    await service.request_password_reset(email="user@example.com")

    body = transport.sent[-1].body
    assert _code_from(transport) in body
    # The wording moved to English on 2026-09-02 with the redesign; the
    # property is unchanged, and is why this assertion exists at all.
    assert "did not ask" in body, "the message must tell an unwitting recipient what it means"


async def test_a_dead_relay_raises_rather_than_lying() -> None:
    """The caller decides what to tell the person; the transport must not decide for it."""
    user = make_user(email="user@example.com")
    service = _service(FakeUserRepository([user]), FakeCodeRepo(), FakeTransport(fails=True))

    with pytest.raises(OSError, match="relay unreachable"):
        await service.request_password_reset(email="user@example.com")


async def test_a_reset_refuses_a_password_from_a_public_breach() -> None:
    """Registration refused these; the reset path used to accept them.

    This is the path where it matters most — the reason a person is resetting
    is often that the old password leaked.
    """
    # Arrange
    users = FakeUserRepository()
    codes = FakeCodeRepo()
    transport = FakeTransport()
    breach = FakePasswordBreachCheck(breached={"password123"})
    service = _service(users, codes, transport, breach)
    user = await users.create(email="seller@example.com", hashed_password="x")
    await service.request_password_reset(email=user.email)
    code = _code_from(transport)

    # Act / Assert
    with pytest.raises(ValidationError):
        await service.reset_password(email=user.email, code=code, new_password="password123")


async def test_the_breach_refusal_is_not_an_account_existence_oracle() -> None:
    """A breached password is refused identically for an address we do not have.

    The check runs BEFORE the account lookup precisely so this holds. Were it
    to run after, a real address would answer "pick another password" and an
    unknown one would answer "wrong code", and the difference would say which
    addresses are registered — the one thing this whole flow is built to hide.
    """
    # Arrange
    users = FakeUserRepository()
    codes = FakeCodeRepo()
    transport = FakeTransport()
    breach = FakePasswordBreachCheck(breached={"password123"})
    service = _service(users, codes, transport, breach)

    # Act / Assert — no such account, and the answer is still the breach one.
    with pytest.raises(ValidationError):
        await service.reset_password(
            email="ghost@example.com", code="000000", new_password="password123"
        )
