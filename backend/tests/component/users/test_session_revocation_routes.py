"""The two ways to end every session of an account, over real HTTP.

Register P1.1 asked for both, and they are different things: one is a user
deciding their own account is not to be trusted, the other is us deciding that
about someone else's. The second is the incident-response lever, so what matters
here is that it is reachable at all — it never was — and that it is reachable
only by a developer.

The revocation semantics themselves (rows revoked, watermark stamped, scoped to
one account) are proved against a real Redis in
``tests/integration/users/test_session_revocation_lever.py``. This tier owns the
wiring: the paths, the guards, and the cookie.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.users.deps import get_token_repo, get_user_repo
from src.modules.users.models import ROLE_DEV
from tests.support.auth import auth_headers, make_user
from tests.support.fakes import FakeRefreshTokenRepository, FakeUserRepository


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Serve the auth routes from in-memory repositories."""
    override(get_user_repo, user_repo)
    override(get_token_repo, token_repo)


async def test_a_user_can_end_all_of_their_own_sessions(
    client: httpx.AsyncClient, user: Any
) -> None:
    """The self-service half: reachable by any authenticated account."""
    response = await client.post("/api/v1/auth/logout-all", headers=auth_headers(user.id))

    assert response.status_code == 200
    assert "revoked" in response.json()


async def test_ending_all_sessions_clears_the_refresh_cookie(
    client: httpx.AsyncClient, user: Any
) -> None:
    """The caller's own browser is signed out too, not left holding a dead cookie.

    Leaving the cookie behind would send the SPA into a refresh that can only
    fail, which reads to the user as a broken app rather than as a logout.
    """
    response = await client.post("/api/v1/auth/logout-all", headers=auth_headers(user.id))

    cookie = response.headers.get("set-cookie", "").lower()
    assert "refresh" in cookie
    assert "max-age=0" in cookie


async def test_an_anonymous_caller_cannot_end_anyone_s_sessions(
    client: httpx.AsyncClient,
) -> None:
    """Otherwise the lever is itself a denial-of-service against any account."""
    response = await client.post("/api/v1/auth/logout-all")

    assert response.status_code == 401


async def test_an_ordinary_user_cannot_revoke_another_account(
    client: httpx.AsyncClient, user: Any
) -> None:
    """The incident lever is not a way for one customer to log another one out."""
    victim = uuid.uuid4()

    response = await client.post(
        f"/api/v1/auth/sessions/{victim}/revoke", headers=auth_headers(user.id)
    )

    assert response.status_code == 403


async def test_a_developer_can_revoke_a_compromised_account(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """The lever exists and answers — which it did not before.

    ``mark_user_sessions_revoked`` had no caller outside the test suite, so the
    watermark could never be set and a stolen session ran to its natural expiry.
    """
    operator = make_user(email="dev@example.com", role=ROLE_DEV)
    user_repo.users[operator.id] = operator
    victim = make_user(email="victim@example.com")
    user_repo.users[victim.id] = victim

    response = await client.post(
        f"/api/v1/auth/sessions/{victim.id}/revoke", headers=auth_headers(operator.id)
    )

    assert response.status_code == 200
    assert response.json()["revoked"] == 0


async def test_revoking_an_unknown_account_is_not_a_lookup_oracle(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """An account that does not exist answers exactly as one with no sessions.

    The route is dev-only, so this is a small thing — but the caller has no use
    for the distinction and an id oracle costs nothing to avoid.
    """
    operator = make_user(email="dev2@example.com", role=ROLE_DEV)
    user_repo.users[operator.id] = operator

    response = await client.post(
        f"/api/v1/auth/sessions/{uuid.uuid4()}/revoke", headers=auth_headers(operator.id)
    )

    assert response.status_code == 200
    assert response.json()["revoked"] == 0
