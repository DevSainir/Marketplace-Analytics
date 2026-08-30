"""Unit tests for login and refresh-token rotation (RTR).

The rules pinned here are the ones an attacker probes:

* login answers identically for "no such user", "wrong password" and "disabled
  account", so the endpoint is not an account-existence oracle;
* every refresh consumes its token and issues a brand-new pair (RTR);
* a rotated session cannot outlive the absolute lifetime ceiling, however often
  it is refreshed.

Breach detection (replaying a consumed token) opens its own committed
transaction on purpose, so it is covered against a real database in
``tests/integration/users/test_breach_detection.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.core.exceptions import AuthenticationError
from src.core.security import hash_refresh_secret
from src.modules.users.services import AuthService
from tests.support.auth import KNOWN_PASSWORD, make_user
from tests.support.fakes import (
    FakeLoginBackoff,
    FakeRefreshTokenRepository,
    FakeUserRepository,
)


def _service(
    users: FakeUserRepository,
    tokens: FakeRefreshTokenRepository | None = None,
    backoff: FakeLoginBackoff | None = None,
) -> AuthService:
    """Build an AuthService over in-memory repositories and a fake backoff."""
    return AuthService(
        user_repo=users,
        token_repo=tokens or FakeRefreshTokenRepository(),
        backoff=backoff or FakeLoginBackoff(),
    )


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
async def test_correct_credentials_issue_a_token_pair() -> None:
    """A valid login returns an access token plus a refresh secret."""
    user = make_user(email="user@example.com")
    service = _service(FakeUserRepository([user]))

    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    assert issued.access_token
    assert issued.refresh_secret
    assert issued.access_expires_at > datetime.now(UTC)


async def test_login_accepts_the_email_in_any_case() -> None:
    """Logins are looked up by the canonical email, matching registration."""
    user = make_user(email="user@example.com")
    service = _service(FakeUserRepository([user]))

    issued = await service.authenticate(email="  USER@Example.com ", password=KNOWN_PASSWORD)

    assert issued.access_token


@pytest.mark.parametrize(
    ("email", "password", "case"),
    [
        ("ghost@example.com", KNOWN_PASSWORD, "unknown account"),
        ("user@example.com", "wrong-password", "wrong password"),
    ],
)
async def test_failed_logins_are_indistinguishable(email: str, password: str, case: str) -> None:
    """Unknown user and wrong password produce the identical error message.

    Any difference here — message, code, or status — turns the endpoint into an
    account-enumeration oracle.
    """
    service = _service(FakeUserRepository([make_user(email="user@example.com")]))

    with pytest.raises(AuthenticationError) as excinfo:
        await service.authenticate(email=email, password=password)

    assert excinfo.value.message == "Invalid email or password."


async def test_a_backed_off_account_is_refused_even_with_the_right_password() -> None:
    """That is what the backoff is: the correct password stops working too.

    Otherwise it bounds nothing — an attacker whose next guess happens to be
    right would be let straight in (register P1.5).
    """
    user = make_user(email="user@example.com")
    backoff = FakeLoginBackoff(penalty=42)
    service = _service(FakeUserRepository([user]), backoff=backoff)

    with pytest.raises(AuthenticationError) as excinfo:
        await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    assert excinfo.value.message == "Invalid email or password."


async def test_a_backed_off_account_answers_exactly_like_a_wrong_password() -> None:
    """The backoff must not become the oracle the generic message avoids.

    "You are being rate limited" tells an attacker the account exists AND that
    the campaign is landing. Both are facts worth withholding.
    """
    known = _service(FakeUserRepository([make_user(email="user@example.com")]))
    with pytest.raises(AuthenticationError) as wrong_password:
        await known.authenticate(email="user@example.com", password="wrong-password")

    blocked = _service(
        FakeUserRepository([make_user(email="user@example.com")]),
        backoff=FakeLoginBackoff(penalty=900),
    )
    with pytest.raises(AuthenticationError) as backed_off:
        await blocked.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    assert backed_off.value.message == wrong_password.value.message
    assert type(backed_off.value) is type(wrong_password.value)


async def test_a_failed_login_is_counted_against_the_account() -> None:
    """Counted on the canonical email, so case variants share one budget."""
    backoff = FakeLoginBackoff()
    service = _service(FakeUserRepository([make_user(email="user@example.com")]), backoff=backoff)

    with pytest.raises(AuthenticationError):
        await service.authenticate(email="  USER@Example.com ", password="wrong-password")

    assert backoff.failures == {"user@example.com": 1}


async def test_an_unknown_account_is_counted_too() -> None:
    """Not counting them would make "no failures recorded" mean "no such user"."""
    backoff = FakeLoginBackoff()
    service = _service(FakeUserRepository([make_user(email="user@example.com")]), backoff=backoff)

    with pytest.raises(AuthenticationError):
        await service.authenticate(email="ghost@example.com", password=KNOWN_PASSWORD)

    assert backoff.failures == {"ghost@example.com": 1}


async def test_a_successful_login_clears_the_run() -> None:
    """Four bad tries then a good one must not leave the account one miss from a penalty."""
    backoff = FakeLoginBackoff()
    service = _service(FakeUserRepository([make_user(email="user@example.com")]), backoff=backoff)

    await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    assert backoff.cleared == ["user@example.com"]


async def test_disabled_account_cannot_log_in() -> None:
    """A soft-disabled account is refused, with the same generic message."""
    disabled = make_user(email="fired@example.com", is_active=False)
    service = _service(FakeUserRepository([disabled]))

    with pytest.raises(AuthenticationError) as excinfo:
        await service.authenticate(email="fired@example.com", password=KNOWN_PASSWORD)

    assert excinfo.value.message == "Invalid email or password."


async def test_a_fresh_login_opens_a_new_token_family() -> None:
    """Logging in twice creates two independent lineages.

    Families are the unit of revocation: if both logins shared one, logging out
    of a phone would kill the desktop session too.
    """
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)

    await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    families = {token.family_id for token in tokens.tokens.values()}
    assert len(families) == 2


# --------------------------------------------------------------------------- #
# Rotation
# --------------------------------------------------------------------------- #
async def test_refresh_issues_a_brand_new_pair_and_consumes_the_old_one() -> None:
    """Rotation is the core RTR contract: new secret out, old secret spent."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    first = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    second = await service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    assert second.refresh_secret != first.refresh_secret
    consumed = await tokens.get_by_hash(hash_refresh_secret(first.refresh_secret))
    assert consumed is not None
    assert consumed.is_used is True


async def test_rotation_stays_inside_the_same_family() -> None:
    """A rotated token continues its lineage rather than starting a new one."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    first = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    await service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    families = {token.family_id for token in tokens.tokens.values()}
    assert len(families) == 1


async def test_rotation_links_the_new_token_to_its_parent() -> None:
    """The chain is recorded, which is what makes a family tree auditable."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    first = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    parent = await tokens.get_by_hash(hash_refresh_secret(first.refresh_secret))

    second = await service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    child = await tokens.get_by_hash(hash_refresh_secret(second.refresh_secret))
    assert parent is not None
    assert child is not None
    assert child.parent_id == parent.id


@pytest.mark.parametrize("secret", [None, "", "never-issued-secret"])
async def test_missing_or_unknown_refresh_secret_is_rejected(secret: str | None) -> None:
    """No cookie, an empty cookie, and a fabricated cookie all fail closed."""
    service = _service(FakeUserRepository([make_user()]))

    with pytest.raises(AuthenticationError):
        await service.rotate_refresh_token(refresh_secret=secret)


async def test_revoked_token_cannot_rotate() -> None:
    """After logout, the cookie left in the browser is inert."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    await service.logout(refresh_secret=issued.refresh_secret)

    with pytest.raises(AuthenticationError, match="revoked"):
        await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)


async def test_expired_token_cannot_rotate() -> None:
    """An expired refresh row is refused even though it was never consumed."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    stored = await tokens.get_by_hash(hash_refresh_secret(issued.refresh_secret))
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(AuthenticationError, match="expired"):
        await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)


async def test_disabled_account_cannot_rotate() -> None:
    """Disabling an account ends its sessions at the next refresh.

    Checking only the token row would let a dismissed employee renew a 7-day
    session indefinitely from a cookie they already hold.
    """
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    user.is_active = False

    with pytest.raises(AuthenticationError, match="disabled"):
        await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)


async def test_session_cannot_outlive_the_absolute_lifetime(settings_override) -> None:
    """Rotation slides the window but cannot extend a family past its ceiling.

    Without this, a stolen-but-never-detected cookie refreshed every six days
    would grant a permanent session.
    """
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    origin = await tokens.get_by_hash(hash_refresh_secret(issued.refresh_secret))
    assert origin is not None
    origin.created_at = datetime.now(UTC) - timedelta(days=31)

    with (
        settings_override(
            session_absolute_lifetime_seconds=int(timedelta(days=30).total_seconds())
        ),
        pytest.raises(AuthenticationError, match="Session lifetime exceeded"),
    ):
        await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)


async def test_refresh_expiry_is_clamped_to_the_session_deadline(settings_override) -> None:
    """Near the ceiling, the new refresh token expires at the deadline, not later.

    The sliding 7-day TTL must not push a token past the family's absolute end.
    """
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    origin = await tokens.get_by_hash(hash_refresh_secret(issued.refresh_secret))
    assert origin is not None
    origin.created_at = datetime.now(UTC) - timedelta(days=29, hours=23)

    with settings_override(
        session_absolute_lifetime_seconds=int(timedelta(days=30).total_seconds()),
        refresh_token_ttl_seconds=int(timedelta(days=7).total_seconds()),
    ):
        rotated = await service.rotate_refresh_token(refresh_secret=issued.refresh_secret)

    assert rotated.refresh_expires_at - datetime.now(UTC) < timedelta(hours=2)


# --------------------------------------------------------------------------- #
# Logout
# --------------------------------------------------------------------------- #
async def test_logout_revokes_the_whole_family() -> None:
    """Logout ends every token in the lineage, not just the presented one."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    first = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    second = await service.rotate_refresh_token(refresh_secret=first.refresh_secret)

    await service.logout(refresh_secret=second.refresh_secret)

    assert all(token.is_revoked for token in tokens.tokens.values())


async def test_logout_ends_the_lineages_access_tokens_too(redis_store) -> None:
    """The point of P1.12: pressing logout stops the stolen token *now*.

    Revoking the refresh rows alone left the access token already handed out
    working for up to its full 15-minute TTL — which is exactly the window
    somebody who presses logout because they think a session is compromised
    cannot afford.
    """
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    family_id = next(iter(tokens.tokens.values())).family_id

    await service.logout(refresh_secret=issued.refresh_secret)

    assert f"auth:family-revoked-after:{family_id}" in redis_store.values


async def test_logout_does_not_touch_the_accounts_other_devices(redis_store) -> None:
    """The per-USER key stays off limits here — that is "log out everywhere"."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    issued = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)

    await service.logout(refresh_secret=issued.refresh_secret)

    assert f"auth:revoked-after:{user.id}" not in redis_store.values


async def test_logging_out_one_browser_leaves_the_other_lineage_alone(redis_store) -> None:
    """Two logins are two families; ending one must not stamp the other."""
    user = make_user(email="user@example.com")
    tokens = FakeRefreshTokenRepository()
    service = _service(FakeUserRepository([user]), tokens)
    phone = await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    await service.authenticate(email="user@example.com", password=KNOWN_PASSWORD)
    families = {token.family_id for token in tokens.tokens.values()}
    assert len(families) == 2, "the two logins must open two lineages"

    await service.logout(refresh_secret=phone.refresh_secret)

    stamped = {
        key.removeprefix("auth:family-revoked-after:")
        for key in redis_store.values
        if key.startswith("auth:family-revoked-after:")
    }
    assert len(stamped) == 1


@pytest.mark.parametrize("secret", [None, "", "never-issued-secret"])
async def test_logout_is_a_silent_no_op_for_unknown_tokens(secret: str | None) -> None:
    """Logout never raises, so it is idempotent and reveals nothing.

    Raising on an unknown secret would confirm which cookies exist and would
    strand a user whose session had already expired on an error page.
    """
    service = _service(FakeUserRepository([make_user()]))

    await service.logout(refresh_secret=secret)
