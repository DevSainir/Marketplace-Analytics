"""Component tests for the access-token guard on protected routes.

The guard is one dependency shared by every module router, so it is tested once
here rather than repeated per module. What matters is that each way of
presenting a bad token ends in a 401 — never a 403, a 422, or a 500, each of
which would leak that the request got further than it should have.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from src.modules.users.deps import get_user_repo
from tests.support.auth import auth_headers, make_access_token
from tests.support.fakes import FakeUserRepository

#: One route per module, so a regression in the shared guard is caught wherever
#: it is mounted rather than only on the auth surface.
GUARDED_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/auth/me"),
    ("GET", "/api/v1/workspaces"),
    ("GET", "/api/v1/monitoring/summary"),
    ("GET", "/api/v1/finreports/weeks"),
]


@pytest.fixture(autouse=True)
def _wire_user_repository(
    override: Callable[[Any, Any], None], user_repo: FakeUserRepository
) -> None:
    """Let ``CurrentUser`` resolve without a database."""
    override(get_user_repo, user_repo)


@pytest.mark.parametrize(("method", "path"), GUARDED_ROUTES)
async def test_missing_authorization_header_is_401(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    """No credentials at all is 401 — not FastAPI's default 403.

    ``HTTPBearer(auto_error=False)`` exists precisely so the API answers with a
    consistent 401 + ``WWW-Authenticate`` instead of a bare 403.
    """
    response = await client.request(method, path)

    assert response.status_code == 401


async def test_unauthenticated_response_advertises_the_scheme(
    client: httpx.AsyncClient,
) -> None:
    """The 401 carries ``WWW-Authenticate: Bearer`` as HTTP requires."""
    response = await client.get("/api/v1/auth/me")

    assert response.headers.get("www-authenticate") == "Bearer"


@pytest.mark.parametrize(("method", "path"), GUARDED_ROUTES)
async def test_garbage_token_is_401(client: httpx.AsyncClient, method: str, path: str) -> None:
    """A malformed bearer value must not reach a route handler."""
    response = await client.request(method, path, headers={"Authorization": "Bearer not.a.jwt"})

    assert response.status_code == 401


async def test_expired_token_is_401(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """A token past its expiry is refused however well-formed it is."""
    principal = next(iter(user_repo.users.values()))
    expired = make_access_token(principal.id, expires_in_seconds=-60)

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401


async def test_token_of_the_wrong_type_is_401(
    client: httpx.AsyncClient, user_repo: FakeUserRepository
) -> None:
    """A correctly signed token minted for another purpose is not an access token."""
    principal = next(iter(user_repo.users.values()))
    wrong_type = make_access_token(principal.id, token_type="refresh")

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {wrong_type}"}
    )

    assert response.status_code == 401


async def test_token_for_a_deleted_user_is_401(client: httpx.AsyncClient) -> None:
    """A valid signature over a vanished account resolves to nobody.

    The token stays cryptographically valid for its full TTL after the row is
    gone; only the database lookup can catch it.
    """
    response = await client.get("/api/v1/auth/me", headers=auth_headers(uuid.uuid4()))

    assert response.status_code == 401


async def test_token_issued_before_a_forced_revocation_is_401(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Breach response kills outstanding access tokens, not just refresh rows.

    Without the ``iat`` watermark check, a stolen access token would keep
    working for up to 15 minutes after "log out everywhere" was triggered.
    """
    from src.core import deps as core_deps

    principal = next(iter(user_repo.users.values()))
    issued_before = make_access_token(
        principal.id, issued_at=datetime.now(UTC) - timedelta(minutes=5)
    )
    revoked_at = datetime.now(UTC) - timedelta(minutes=1)

    async def _revoked(user_id: uuid.UUID) -> datetime:
        return revoked_at

    monkeypatch.setattr(core_deps, "sessions_revoked_after", _revoked)

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {issued_before}"}
    )

    assert response.status_code == 401


async def test_token_issued_after_a_revocation_still_works(
    client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logging back in after a global logout must work immediately.

    The watermark invalidates *older* tokens only; if it rejected newer ones too,
    a breach response would lock the legitimate owner out for 15 minutes.
    """
    from src.core import deps as core_deps

    principal = next(iter(user_repo.users.values()))
    revoked_at = datetime.now(UTC) - timedelta(minutes=5)

    async def _revoked(user_id: uuid.UUID) -> datetime:
        return revoked_at

    monkeypatch.setattr(core_deps, "sessions_revoked_after", _revoked)

    response = await client.get("/api/v1/auth/me", headers=auth_headers(principal.id))

    assert response.status_code == 200


async def test_health_probe_stays_public(client: httpx.AsyncClient) -> None:
    """The liveness endpoint must not require a token.

    An authenticated probe would make every orchestrator restart the container.
    """
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
