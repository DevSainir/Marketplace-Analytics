"""Component tests for the auth surface over real HTTP.

Everything below the repository boundary is real here: the router, the
dependency graph, the ``AuthService``, cookie handling, and the global
``AppError`` → status mapping in ``main.py``. What the unit tier cannot show is
exactly this wiring — that a ``ConflictError`` becomes a 409, that the refresh
secret leaves as an HttpOnly cookie and never in the JSON body, and that
``/refresh`` actually reads the cookie name the app writes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.config import settings
from src.modules.users.deps import get_token_repo, get_user_repo
from tests.support.auth import KNOWN_PASSWORD, auth_headers, make_user
from tests.support.fakes import FakeRefreshTokenRepository, FakeUserRepository


@pytest.fixture(autouse=True)
def _wire_auth_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Serve the auth routes from in-memory repositories."""
    override(get_user_repo, user_repo)
    override(get_token_repo, token_repo)


# --------------------------------------------------------------------------- #
# POST /register
# --------------------------------------------------------------------------- #
async def test_register_returns_201_with_the_public_account(
    client: httpx.AsyncClient,
) -> None:
    """A valid signup answers 201 and the account DTO — never a token."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": "a-long-password"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "user"
    assert "hashed_password" not in body
    assert "access_token" not in body


async def test_register_with_a_taken_email_is_409(
    client: httpx.AsyncClient,
) -> None:
    """``ConflictError`` reaches the client as 409 with its machine code."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",  # seeded by the `user` fixture
            "password": "a-long-password",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "a-long-password"},
        {"email": "a@example.com", "password": "short"},
        {"email": "a@example.com"},
        {"email": "a@example.com", "password": "я" * 40},
    ],
    ids=[
        "malformed-email",
        "password-too-short",
        "missing-password",
        "password-over-72-bytes",
    ],
)
async def test_register_rejects_malformed_payloads(
    client: httpx.AsyncClient, payload: dict[str, str]
) -> None:
    """Schema validation answers 422 before any business logic runs."""
    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# POST /login
# --------------------------------------------------------------------------- #
async def test_login_returns_an_access_token_and_sets_the_refresh_cookie(
    client: httpx.AsyncClient,
) -> None:
    """The two halves travel separately: token in JSON, secret in the cookie."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": KNOWN_PASSWORD},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert "refresh" not in str(body).lower()
    assert settings.refresh_cookie_name in response.cookies


async def test_refresh_cookie_is_hardened(client: httpx.AsyncClient) -> None:
    """HttpOnly + SameSite=Lax + a scoped path — the XSS/CSRF posture.

    Without HttpOnly a single XSS reads the refresh secret and owns the session
    for seven days; without the path scope it is sent to every API route.
    """
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": KNOWN_PASSWORD},
    )

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert f"Path={settings.refresh_cookie_path}" in set_cookie


async def test_login_with_wrong_password_is_401(client: httpx.AsyncClient) -> None:
    """``AuthenticationError`` maps to 401 with the generic message."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


async def test_login_for_an_unknown_account_is_indistinguishable(
    client: httpx.AsyncClient,
) -> None:
    """An unknown email produces byte-identical output to a wrong password.

    Any divergence in status, code, or message turns the endpoint into an
    account-enumeration oracle.
    """
    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    unknown_user = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "wrong-password"},
    )

    assert unknown_user.status_code == wrong_password.status_code
    assert unknown_user.json() == wrong_password.json()


# --------------------------------------------------------------------------- #
# POST /refresh
# --------------------------------------------------------------------------- #
async def test_refresh_rotates_the_pair_using_the_cookie(client: httpx.AsyncClient) -> None:
    """The client sends no body — the cookie alone drives rotation.

    This also proves ``/refresh`` reads the same configurable cookie name the
    login writes; a hard-coded parameter name would break the day it changed.
    """
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": KNOWN_PASSWORD},
    )
    original_secret = login.cookies[settings.refresh_cookie_name]

    rotated = await client.post("/api/v1/auth/refresh")

    assert rotated.status_code == 200
    assert rotated.json()["access_token"]
    assert rotated.cookies[settings.refresh_cookie_name] != original_secret


async def test_refresh_without_a_cookie_is_401(client: httpx.AsyncClient) -> None:
    """A cold client with no session gets 401, not a 422 for a missing field."""
    response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# GET /me
# --------------------------------------------------------------------------- #
async def test_me_returns_the_authenticated_account(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """The route resolves the token's subject to the live account row."""
    principal = next(iter(user_repo.users.values()))

    response = await client.get("/api/v1/auth/me", headers=auth_headers(principal.id))

    assert response.status_code == 200
    assert response.json()["email"] == principal.email


async def test_me_reflects_a_role_change_without_a_new_token(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """Roles are read from the database per request, not from the token.

    A revoked role must take effect on the next request, not after the 15-minute
    access-token TTL.
    """
    principal = make_user(email="promotable@example.com")
    user_repo.users[principal.id] = principal
    headers = auth_headers(principal.id)
    principal.role = "dev"

    response = await client.get("/api/v1/auth/me", headers=headers)

    assert response.json()["role"] == "dev"


async def test_me_rejects_a_deactivated_account(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """Disabling an account invalidates its still-valid access token at once."""
    principal = make_user(email="fired@example.com", is_active=False)
    user_repo.users[principal.id] = principal

    response = await client.get("/api/v1/auth/me", headers=auth_headers(principal.id))

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# POST /logout
# --------------------------------------------------------------------------- #
async def test_logout_clears_the_cookie_and_revokes_the_family(
    client: httpx.AsyncClient, token_repo: FakeRefreshTokenRepository
) -> None:
    """204 with an expiring cookie, and the server-side session is dead."""
    await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": KNOWN_PASSWORD},
    )

    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    assert all(token.is_revoked for token in token_repo.tokens.values())
    assert "Max-Age=0" in response.headers["set-cookie"]


async def test_logout_without_a_session_still_succeeds(client: httpx.AsyncClient) -> None:
    """Logout is idempotent — a stale tab must not land on an error page."""
    response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 204
