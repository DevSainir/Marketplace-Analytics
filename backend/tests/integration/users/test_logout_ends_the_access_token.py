"""Logout stops the access token it was pressed about.

Everything below this test already worked: logout revoked the family's refresh
rows, so no *new* pair could be minted. What it did not do was stop the access
token already handed out, which stayed valid for up to its full fifteen minutes.
The register carried that as documented and accepted. It is neither, for the
case logout exists for — someone who thinks a session is compromised presses the
button, and fifteen more minutes of an attacker inside the account is precisely
what they pressed it to prevent.

That gap can only be shown end to end: it lives in the gap between what the
service writes (Redis) and what the request path reads on the next call, so a
test of either half alone would have passed throughout. These go through the
real app against a real Redis, and the second one is the reason the fix is
scoped per *family* rather than per user — closing the window must not sign the
customer's other devices out.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import hash_password
from src.modules.users.models import ROLE_USER, User

pytestmark = pytest.mark.integration

PASSWORD = "a-long-enough-password"
PROTECTED = "/api/v1/organizations/me"


@pytest.fixture(autouse=True)
def _isolated_redis(redis_client: Any) -> None:
    """A per-test Redis client, on the test index.

    The watermarks under test live in Redis, and the shared client would
    otherwise hand the next test connections bound to this test's event loop.
    """


async def _account(session: AsyncSession) -> User:
    """Persist an active account with a known password."""
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password(PASSWORD),
        # Confirmed: `/login` refuses an unproven address, so an account a
        # test authenticates as has to be one.
        email_confirmed_at=datetime.now(UTC),
        role=ROLE_USER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _login(client: Any, user: User) -> tuple[str, str]:
    """Log in and return ``(access token, refresh cookie)``."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"], response.cookies["refresh_token"]


async def test_the_access_token_stops_working_the_moment_you_log_out(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """The whole of P1.12, in four calls."""
    # Arrange
    user = await _account(db_session)
    access, refresh = await _login(api_client, user)
    before = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {access}"})
    assert before.status_code == 200, "the token must work first, or the test proves nothing"

    # Act
    logout = await api_client.post("/api/v1/auth/logout", cookies={"refresh_token": refresh})

    # Assert
    assert logout.status_code == 204, logout.text
    after = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {access}"})
    assert after.status_code == 401


async def test_logging_out_one_browser_leaves_the_other_signed_in(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """Why the watermark is per-family and never per-user.

    Stamping the account-wide key here would make "log out of this browser" sign
    the customer's phone out mid-task — the same blast radius that turned one
    replayed token into a team-wide outage on 2026-07-27.
    """
    # Arrange
    user = await _account(db_session)
    laptop_access, laptop_refresh = await _login(api_client, user)
    phone_access, _ = await _login(api_client, user)

    # Act
    logout = await api_client.post("/api/v1/auth/logout", cookies={"refresh_token": laptop_refresh})

    # Assert
    assert logout.status_code == 204, logout.text
    laptop = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {laptop_access}"})
    phone = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {phone_access}"})
    assert laptop.status_code == 401
    assert phone.status_code == 200


async def test_logging_out_everywhere_still_ends_every_device(
    api_client: Any,
    db_session: AsyncSession,
) -> None:
    """The wide lever must keep being wide — the narrow one did not replace it."""
    # Arrange
    user = await _account(db_session)
    laptop_access, _ = await _login(api_client, user)
    phone_access, _ = await _login(api_client, user)

    # Act
    response = await api_client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {phone_access}"},
    )

    # Assert
    assert response.status_code == 200, response.text
    laptop = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {laptop_access}"})
    phone = await api_client.get(PROTECTED, headers={"Authorization": f"Bearer {phone_access}"})
    assert laptop.status_code == 401
    assert phone.status_code == 401


async def test_a_replayed_refresh_token_ends_its_lineages_access_tokens(
    api_client: Any,
    db_session: AsyncSession,
    settings_override: Any,
) -> None:
    """A detected replay is the strongest evidence the lineage is compromised.

    It was the last place still waiting out a 15-minute TTL: the family's
    refresh rows were revoked on detection, while the access token minted from
    the very token being replayed kept working.

    The grace window is set to zero, which is its documented "strict rotation"
    value rather than a test-only switch. With the default 30 s an immediate
    replay is *deliberately* not a breach — three tabs share one cookie and each
    fires /refresh on load — so this test would otherwise be
    asserting against the concurrency feature instead of against breach
    handling. The grace path has its own coverage in
    ``test_concurrent_tab_refresh.py``.
    """
    # Arrange
    user = await _account(db_session)
    with settings_override(refresh_replay_grace_seconds=0):
        _, first_refresh = await _login(api_client, user)
        rotated = await api_client.post(
            "/api/v1/auth/refresh", cookies={"refresh_token": first_refresh}
        )
        assert rotated.status_code == 200, rotated.text
        rotated_access = rotated.json()["access_token"]

        # Act — present the already-consumed token again.
        replay = await api_client.post(
            "/api/v1/auth/refresh", cookies={"refresh_token": first_refresh}
        )

        # Assert
        assert replay.status_code == 401, replay.text
        after = await api_client.get(
            PROTECTED, headers={"Authorization": f"Bearer {rotated_access}"}
        )
        assert after.status_code == 401
