"""Password reset through the real routes, against a real database (P1.6).

The unit tier pins the rules. This pins the two things only the whole stack can
show, and both are the reasons the register said building this badly is worse
than not having it:

**A completed reset ends every session, everywhere.** The case this feature
exists for is "somebody else may have my password". Changing the password while
leaving their sessions alive hands the attacker exactly what the reset was meant
to take away — and that failure lives in the gap between the recovery service
(which does not revoke) and the router (which does), so no unit test of either
half would catch it.

**The endpoints disclose nothing.** A registered address, an unknown one and a
disabled account must be indistinguishable from the outside — same status, same
body. That is a property of the HTTP response, not of a service return value.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password
from src.modules.users.models import ROLE_USER, User

pytestmark = pytest.mark.integration

PASSWORD = "a-long-enough-password"
NEW_PASSWORD = "an-even-better-password"
PROTECTED = "/api/v1/organizations/me"


class CapturingTransport:
    """Keeps every message the flow sends, so a test can read the code.

    This replaces the transport through the app's own DI seam rather than
    scraping the application log. Reading the log worked in isolation and lost
    records once the whole tier ran — `configure_logging` is process-wide and
    another test reconfiguring it is enough — and a test that depends on log
    formatting is testing the wrong thing anyway.
    """

    def __init__(self) -> None:
        """Start with nothing sent."""
        self.sent: list[Any] = []

    async def send(self, message: Any) -> None:
        """Record the message."""
        self.sent.append(message)

    def latest_code(self) -> str:
        """Return the code from the most recent message."""
        assert self.sent, "nothing was sent"
        return next(
            part for part in self.sent[-1].body.split() if part.isdigit() and len(part) >= 6
        )


@pytest.fixture
def mailbox() -> CapturingTransport:
    """The transport every test in this file sends through."""
    return CapturingTransport()


@pytest.fixture(autouse=True)
def _reset_enabled(redis_client: Any, settings_override: Any, mailbox: CapturingTransport) -> Any:
    """Turn the flow on, capture its mail, and isolate Redis.

    ``password_reset_enabled`` defaults OFF — it ships dark until a relay exists
    (register P1.6) — so these tests enable it explicitly. ``email_enabled``
    stays off, so nothing here can reach a network even if the override failed.
    """
    from main import app
    from src.modules.users.deps import get_email_transport_dep

    app.dependency_overrides[get_email_transport_dep] = lambda: mailbox
    try:
        with settings_override(password_reset_enabled=True):
            yield
    finally:
        app.dependency_overrides.pop(get_email_transport_dep, None)


async def _account(session: AsyncSession, *, active: bool = True) -> User:
    """Persist an account with a known password."""
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(PASSWORD),
        role=ROLE_USER,
        is_active=active,
    )
    session.add(user)
    await session.flush()
    return user


async def _login(client: Any, user: User, password: str = PASSWORD) -> str:
    """Log in and return the access token."""
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def test_a_reset_ends_every_session_on_every_device(
    api_client: Any,
    db_session: AsyncSession,
    mailbox: CapturingTransport,
) -> None:
    """The half that lives between the service and the router.

    Two devices signed in, one reset, and BOTH tokens must die — including the
    one belonging to whoever is doing the resetting.
    """
    # Arrange
    user = await _account(db_session)
    laptop = await _login(api_client, user)
    phone = await _login(api_client, user)

    requested = await api_client.post(
        "/api/v1/auth/password-reset/request", json={"email": user.email}
    )
    assert requested.status_code == 202, requested.text
    code = mailbox.latest_code()

    # Act
    done = await api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"email": user.email, "code": code, "new_password": NEW_PASSWORD},
    )

    # Assert
    assert done.status_code == 200, done.text
    for token in (laptop, phone):
        after = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {token}"})
        assert after.status_code == 401
    assert await _login(api_client, user, NEW_PASSWORD)


async def test_the_old_password_stops_working(
    api_client: Any,
    db_session: AsyncSession,
    mailbox: CapturingTransport,
) -> None:
    """Obvious, and catastrophic if it were ever untrue."""
    # Arrange
    user = await _account(db_session)
    await api_client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    code = mailbox.latest_code()

    # Act
    await api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"email": user.email, "code": code, "new_password": NEW_PASSWORD},
    )

    # Assert
    stale = await api_client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    assert stale.status_code == 401


async def test_a_wrong_code_is_refused_and_changes_nothing(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """A guess must cost an attempt and leave the credential alone."""
    # Arrange
    user = await _account(db_session)
    await api_client.post("/api/v1/auth/password-reset/request", json={"email": user.email})

    # Act
    response = await api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"email": user.email, "code": "000000", "new_password": NEW_PASSWORD},
    )

    # Assert
    assert response.status_code == 422
    assert await _login(api_client, user, PASSWORD)


async def test_the_request_endpoint_answers_identically_for_every_address(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """Registered, unknown and disabled must be indistinguishable.

    Otherwise this is `/login`'s account-existence oracle, reachable without
    even a password guess.
    """
    # Arrange
    live = await _account(db_session)
    disabled = await _account(db_session, active=False)

    # Act
    responses = [
        await api_client.post("/api/v1/auth/password-reset/request", json={"email": address})
        for address in (live.email, disabled.email, "nobody-at-all@example.com")
    ]

    # Assert
    assert {r.status_code for r in responses} == {202}
    assert len({r.text for r in responses}) == 1


async def test_confirming_an_address_answers_identically_for_every_failure(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """Same rule on the confirmation side: a wrong code and no account agree."""
    # Arrange
    user = await _account(db_session)

    # Act
    wrong_code = await api_client.post(
        "/api/v1/auth/confirm-email", json={"email": user.email, "code": "000000"}
    )
    no_account = await api_client.post(
        "/api/v1/auth/confirm-email",
        json={"email": "nobody-at-all@example.com", "code": "000000"},
    )

    # Assert
    assert wrong_code.status_code == no_account.status_code == 422
    assert wrong_code.json() == no_account.json()


async def test_registration_mails_a_code_that_confirms_the_address(
    api_client: Any,
    mailbox: CapturingTransport,
) -> None:
    """The registration half of the feature, end to end."""
    # Arrange
    email = f"fresh-{uuid.uuid4().hex[:8]}@example.com"

    # Act
    created = await api_client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert created.status_code == 201, created.text
    code = mailbox.latest_code()

    confirmed = await api_client.post(
        "/api/v1/auth/confirm-email", json={"email": email, "code": code}
    )

    # Assert
    assert confirmed.status_code == 200, confirmed.text


async def test_the_flow_is_dark_when_it_is_switched_off(
    api_client: Any,
    db_session: AsyncSession,
    settings_override: Any,
) -> None:
    """Off must still answer 202 — a different answer says the feature is off.

    That is a small disclosure, but the uniform answer costs nothing and this
    endpoint's entire job is to be uniform.
    """
    # Arrange
    user = await _account(db_session)

    # Act
    with settings_override(password_reset_enabled=False):
        requested = await api_client.post(
            "/api/v1/auth/password-reset/request", json={"email": user.email}
        )
        confirmed = await api_client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"email": user.email, "code": "000000", "new_password": NEW_PASSWORD},
        )

    # Assert
    assert requested.status_code == 202
    assert confirmed.status_code == 422
    assert await _login(api_client, user, PASSWORD)


async def test_a_completed_reset_is_recorded_in_the_audit_log(
    api_client: Any,
    db_session: AsyncSession,
    mailbox: CapturingTransport,
) -> None:
    """`PASSWORD_CHANGED` had a name in the vocabulary and nothing emitting it.

    A password changing with no login is the most useful line in the trail when
    the question afterwards is how somebody got in. It is asserted end to end
    because the actor is the part that could plausibly be lost: the route is
    unauthenticated, so the recorder arrives with no actor and the identity has
    to be handed to it. A row with a null actor would look like a working audit
    trail and answer nothing.
    """
    # Arrange
    user = await _account(db_session)
    requested = await api_client.post(
        "/api/v1/auth/password-reset/request", json={"email": user.email}
    )
    assert requested.status_code == 202, requested.text

    # Act
    done = await api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"email": user.email, "code": mailbox.latest_code(), "new_password": NEW_PASSWORD},
    )

    # Assert
    assert done.status_code == 200, done.text
    row = (
        (
            await db_session.execute(
                sa.text(
                    "SELECT actor_user_id, actor_email, target_id, ip_address, metadata "
                    "FROM organizations.audit_log WHERE event = 'PASSWORD_CHANGED' "
                    "ORDER BY occurred_at DESC LIMIT 1"
                )
            )
        )
        .mappings()
        .first()
    )
    assert row is not None, "the reset was not recorded"
    assert row["actor_user_id"] == user.id, "recorded with no actor — the row answers nothing"
    assert row["actor_email"] == user.email
    assert str(row["target_id"]) == str(user.id)
    assert row["ip_address"], "the address is the half the account holder cannot tell you"
    assert row["metadata"]["via"] == "password-reset"


async def test_a_refused_reset_records_nothing(
    api_client: Any,
    db_session: AsyncSession,
    mailbox: CapturingTransport,
) -> None:
    """An audit trail that records attempts as if they succeeded is worse than none.

    The wrong-code path returns 422 before the password changes; nothing about
    it belongs under `PASSWORD_CHANGED`, and a reader scanning for that event
    during an incident must be able to trust every hit.
    """
    # Arrange
    user = await _account(db_session)
    await api_client.post("/api/v1/auth/password-reset/request", json={"email": user.email})
    before = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM organizations.audit_log WHERE event = 'PASSWORD_CHANGED'")
        )
    ).scalar_one()

    # Act
    refused = await api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"email": user.email, "code": "000000", "new_password": NEW_PASSWORD},
    )

    # Assert
    assert refused.status_code == 422, refused.text
    after = (
        await db_session.execute(
            sa.text("SELECT count(*) FROM organizations.audit_log WHERE event = 'PASSWORD_CHANGED'")
        )
    ).scalar_one()
    assert after == before
