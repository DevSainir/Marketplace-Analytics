"""The auth rate limiter must not be resettable by a request header.

Register item P0.1. The limiter used to key on ``request.client.host``, which in
production is written by uvicorn's proxy middleware — running in always-trust
mode (``--forwarded-allow-ips "*"``), where it takes the **leftmost**
``X-Forwarded-For`` entry. nginx appended the real address to whatever the
client sent, so the leftmost entry was the client's own invention: a new
counter key per request, and unlimited password brute-force on ``/login``.

The app is therefore wrapped here in the **real** ``ProxyHeadersMiddleware``
with production's trust setting. Without it this tier speaks ASGI directly and
``client`` is whatever httpx chose, so a spoofed header could not affect the
outcome and the test would pass against the very bug it is meant to catch. It
also pins uvicorn's semantics, which changed once already between 0.29 and 0.30.

nginx no longer forwards the client's chain at all (``proxy-headers.conf`` sets
both address headers from ``$remote_addr``). These tests deliberately model the
world *without* that fix — the backend must hold on its own.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.core.config import settings
from src.modules.users.deps import get_token_repo, get_user_repo
from tests.support.auth import KNOWN_PASSWORD, make_user
from tests.support.fakes import FakeRefreshTokenRepository, FakeUserRepository

#: The address nginx would write into X-Real-IP: the true origin of the request.
TRUE_CLIENT = "203.0.113.7"

#: What nginx itself looks like from inside the Docker network.
PROXY_PEER = "172.18.0.5"


@pytest.fixture(autouse=True)
def _wire_auth_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    token_repo: FakeRefreshTokenRepository,
) -> None:
    """Serve the auth routes from in-memory repositories."""
    override(get_user_repo, user_repo)
    override(get_token_repo, token_repo)


@pytest.fixture
async def proxied_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Yield a client whose requests pass through production's proxy middleware.

    ``trusted_hosts="*"`` mirrors ``--forwarded-allow-ips "*"`` in
    ``docker-compose.yml``, and the transport's peer is the nginx container, so
    the scope reaching the app is the one the real deployment builds.

    Yields:
        An HTTP client speaking to the wrapped app.
    """
    transport = httpx.ASGITransport(
        app=ProxyHeadersMiddleware(app, trusted_hosts="*"),
        client=(PROXY_PEER, 43210),
    )
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as ac:
        yield ac


def _login_as(spoof: str) -> dict[str, str]:
    """Build the headers of a login attempt carrying a forged forwarded chain.

    Args:
        spoof: The address the attacker puts in ``X-Forwarded-For``.

    Returns:
        Headers as the app would see them behind a proxy that forwarded the
        client's chain — the pre-fix nginx behaviour.
    """
    return {"X-Real-IP": TRUE_CLIENT, "X-Forwarded-For": spoof}


async def test_a_forged_forwarded_header_does_not_escape_a_spent_budget(
    proxied_client: httpx.AsyncClient,
    redis_store: Any,
) -> None:
    """A client whose budget is spent stays throttled however it forges the chain.

    This is the bypass itself: keyed on the forged value, the attempt below
    opened a brand-new counter and answered 401, and the attacker simply changed
    the header again for the next password.
    """
    spent_key = f"ratelimit:auth:{TRUE_CLIENT}"
    redis_store.counters[spent_key] = settings.auth_rate_limit_attempts

    response = await proxied_client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "guess-1"},
        headers=_login_as("198.51.100.1"),
    )

    assert response.status_code == 429


async def test_every_forged_chain_lands_on_the_same_counter(
    proxied_client: httpx.AsyncClient,
    redis_store: Any,
) -> None:
    """Two attempts forging different chains spend one shared budget, not two.

    Asserting on the key set rather than a status code shows the property that
    matters — the attacker cannot *mint* keys — independently of how many
    attempts the configured budget happens to allow. The budget starts spent so
    both attempts are rejected at the dependency: they are still counted, but
    neither reaches the password hash, which keeps this inside the tier budget.
    """
    spent_key = f"ratelimit:auth:{TRUE_CLIENT}"
    redis_store.counters[spent_key] = settings.auth_rate_limit_attempts

    await proxied_client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "guess-1"},
        headers=_login_as("198.51.100.1"),
    )
    await proxied_client.post(
        "/api/v1/auth/login",
        json={"email": "victim@example.com", "password": "guess-2"},
        headers=_login_as("198.51.100.2"),
    )

    auth_keys = {
        key: value
        for key, value in redis_store.counters.items()
        if key.startswith("ratelimit:auth:")
    }
    assert auth_keys == {spent_key: settings.auth_rate_limit_attempts + 2}


async def test_a_real_login_still_succeeds_behind_the_proxy(
    proxied_client: httpx.AsyncClient,
    user_repo: FakeUserRepository,
) -> None:
    """The resolution change must not break the ordinary proxied login path.

    A control that keys on a header is one header away from throttling everyone;
    this pins that the normal case still reaches the service and authenticates.
    """
    member = make_user(email="member@example.com")
    user_repo.users[member.id] = member

    response = await proxied_client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": KNOWN_PASSWORD},
        headers=_login_as("198.51.100.1"),
    )

    assert response.status_code == 200
