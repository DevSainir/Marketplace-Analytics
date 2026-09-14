"""Component tests for the session list, ending one, and changing a password.

What only this tier can show: that the routes are wired to the right guard,
that the response DTOs carry no secret, and that "which session am I" is read
from the token's ``fam`` claim rather than guessed.

The 404-not-403 rule for somebody else's lineage is asserted here as an HTTP
status, because that is the form it is actually observed in — a unit test can
prove the exception type and not the status the caller sees.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from src.core.ids import uuid7
from src.modules.users.deps import get_token_repo, get_user_repo
from tests.support.auth import KNOWN_PASSWORD, auth_headers, make_user
from tests.support.fakes import FakeRefreshTokenRepository, FakeUserRepository

NEW_PASSWORD = "Sovsem-Drugoj-2026"


@pytest.fixture(autouse=True)
def _wire_auth_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Serve the auth routes from in-memory repositories."""
    override(get_user_repo, user_repo)
    override(get_token_repo, token_repo)


async def _open(token_repo: FakeRefreshTokenRepository, user_id, family_id, **extra) -> None:
    """Give an account one live refresh row on the named lineage."""
    await token_repo.create(
        token_id=uuid7(),
        user_id=user_id,
        family_id=family_id,
        token_hash=f"hash-{uuid7()}",
        expires_at=datetime.now(UTC) + timedelta(days=7),
        **extra,
    )


# --------------------------------------------------------------------------- #
# GET /sessions
# --------------------------------------------------------------------------- #
async def test_the_list_marks_the_session_that_is_asking(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """`is_current` comes from the token's own `fam` claim, not from the order."""
    user = make_user()
    user_repo.users[user.id] = user
    mine, other = uuid7(), uuid7()
    await _open(token_repo, user.id, mine, user_agent="Mozilla/5.0 (Macintosh)")
    await _open(token_repo, user.id, other, user_agent="Mozilla/5.0 (iPhone)")

    response = await client.get(
        "/api/v1/auth/sessions", headers=auth_headers(user.id, family_id=mine)
    )

    assert response.status_code == 200
    rows = {row["family_id"]: row for row in response.json()}
    assert rows[str(mine)]["is_current"] is True
    assert rows[str(other)]["is_current"] is False


async def test_a_token_with_no_lineage_marks_nothing_current(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Unknown is not "yes" — otherwise the UI offers to end the browser you are in."""
    user = make_user()
    user_repo.users[user.id] = user
    await _open(token_repo, user.id, uuid7())

    response = await client.get("/api/v1/auth/sessions", headers=auth_headers(user.id))

    assert response.status_code == 200
    assert all(row["is_current"] is False for row in response.json())


async def test_the_list_carries_no_secret(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """A session DTO names the lineage and nothing that could authenticate."""
    user = make_user()
    user_repo.users[user.id] = user
    await _open(token_repo, user.id, uuid7())

    response = await client.get("/api/v1/auth/sessions", headers=auth_headers(user.id))

    row = response.json()[0]
    assert set(row) == {
        "family_id",
        "user_agent",
        "ip_address",
        "started_at",
        "last_seen_at",
        "is_current",
    }


async def test_the_list_never_shows_another_account(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Scoped by the caller, not filtered afterwards."""
    user, stranger = make_user(), make_user(email="stranger@example.com")
    user_repo.users[user.id] = user
    user_repo.users[stranger.id] = stranger
    await _open(token_repo, stranger.id, uuid7())

    response = await client.get("/api/v1/auth/sessions", headers=auth_headers(user.id))

    assert response.json() == []


async def test_the_list_needs_a_token(client: httpx.AsyncClient) -> None:
    """No guard means no list."""
    response = await client.get("/api/v1/auth/sessions")

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# DELETE /sessions/{family_id}
# --------------------------------------------------------------------------- #
async def test_ending_a_session_revokes_only_that_lineage(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """«Завершить сеанс» on one device leaves the others signed in."""
    user = make_user()
    user_repo.users[user.id] = user
    phone, laptop = uuid7(), uuid7()
    await _open(token_repo, user.id, phone)
    await _open(token_repo, user.id, laptop)

    response = await client.delete(
        f"/api/v1/auth/sessions/{phone}", headers=auth_headers(user.id, family_id=laptop)
    )

    assert response.status_code == 204
    live = {t.family_id for t in token_repo.tokens.values() if not t.is_revoked}
    assert live == {laptop}


async def test_ending_a_stranger_s_session_is_404(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """403 would confirm the lineage exists; 404 tells the caller nothing."""
    user, stranger = make_user(), make_user(email="stranger@example.com")
    user_repo.users[user.id] = user
    user_repo.users[stranger.id] = stranger
    theirs = uuid7()
    await _open(token_repo, stranger.id, theirs)

    response = await client.delete(f"/api/v1/auth/sessions/{theirs}", headers=auth_headers(user.id))

    assert response.status_code == 404
    assert all(not t.is_revoked for t in token_repo.tokens.values())


# --------------------------------------------------------------------------- #
# POST /password
# --------------------------------------------------------------------------- #
async def test_changing_the_password_ends_the_other_sessions(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """The whole point of the route, over real HTTP."""
    user = make_user()
    user_repo.users[user.id] = user
    mine, phone = uuid7(), uuid7()
    await _open(token_repo, user.id, mine)
    await _open(token_repo, user.id, phone)

    response = await client.post(
        "/api/v1/auth/password",
        headers=auth_headers(user.id, family_id=mine),
        json={"current_password": KNOWN_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json() == {"other_sessions_ended": 1}
    live = {t.family_id for t in token_repo.tokens.values() if not t.is_revoked}
    assert live == {mine}


async def test_the_wrong_current_password_is_401(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
) -> None:
    """A live session is not on its own enough to replace the password."""
    user = make_user()
    user_repo.users[user.id] = user

    response = await client.post(
        "/api/v1/auth/password",
        headers=auth_headers(user.id),
        json={"current_password": "nope", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401


async def test_a_weak_new_password_is_refused_without_echoing_it(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
) -> None:
    """422 says which field and why — never what was submitted."""
    user = make_user()
    user_repo.users[user.id] = user
    rejected = "vsestrochnye"

    response = await client.post(
        "/api/v1/auth/password",
        headers=auth_headers(user.id),
        json={"current_password": KNOWN_PASSWORD, "new_password": rejected},
    )

    assert response.status_code == 422
    assert rejected not in response.text


async def test_changing_a_password_needs_a_token(client: httpx.AsyncClient) -> None:
    """Anonymous callers use the mailed-code reset, not this."""
    response = await client.post(
        "/api/v1/auth/password",
        json={"current_password": KNOWN_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401
