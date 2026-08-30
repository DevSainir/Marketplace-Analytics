"""Component-tier fixtures: the real ASGI app with persistence faked out.

What this tier proves, and the unit tier cannot: the wiring. Route paths,
dependency graph, auth/tenancy/role guards, request validation, response-model
shaping, cookie handling, and the ``AppError`` → HTTP status mapping installed
in ``main.py``. Everything below the service boundary is an in-memory fake, so
the whole tier runs without Postgres, Redis, or Celery.

The app is imported once per session (importing ``main`` builds the entire
router graph); each test gets its own dependency overrides and its own fakes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from src.core.deps import get_db
from src.modules.organizations.contract import (
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
)
from src.modules.organizations.deps import get_current_access
from src.modules.users.deps import get_current_user
from src.modules.users.models import ROLE_DEV, User
from src.modules.workspaces.models import Workspace
from tests.support.auth import make_user
from tests.support.fakes import (
    FakeRedis,
    FakeRefreshTokenRepository,
    FakeUserRepository,
    FakeWorkspaceRepository,
    FakeWorkspaceTokenRepository,
    make_workspace,
)


@pytest.fixture(scope="session")
def app() -> FastAPI:
    """Return the real FastAPI application with every module router mounted."""
    from main import app as fastapi_app

    return fastapi_app


@pytest.fixture(autouse=True)
def redis_store(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Back every Redis-backed control in this tier with one in-memory store.

    ONE fixture, because there is one seam. Every caller resolves the client by
    calling ``get_redis()``, which reads this module global at call time, so
    replacing it redirects the rate limiter, the «Обновить» task binding and its
    enqueue budget, the refresh replay-grace window and the session-revocation
    watermark together — and, more to the point, redirects the next control
    somebody adds without anyone remembering to come back here.

    This used to be four fixtures, one per caller, and the fourth was written
    only after a new route reached a live Redis and failed as ``Event loop is
    closed`` from a second event loop. ``get_redis`` is now the single accessor,
    enforced by ``tests/unit/core/test_redis_single_accessor.py``.

    The store is shared rather than partitioned, which is also what production
    looks like: one Redis, keys namespaced by their owner
    (``ratelimit:``, ``monitoring:refresh-task:``, ``auth:refresh-grace:``,
    ``auth:revoked-after:``).

    Returns:
        The store, so a test can pre-load a counter or inspect what was written.
    """
    from src.core import redis as core_redis

    store = FakeRedis()
    monkeypatch.setattr(core_redis, "_redis", store)
    return store


@pytest.fixture(autouse=True)
def _no_session_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report "no revocation in force" without touching Redis.

    ``get_current_user_id`` consults the Redis watermark on every authenticated
    request. The revocation semantics are covered against a real Redis in
    ``tests/integration/core/test_session_revocation.py``.
    """
    from src.core import deps as core_deps

    async def _never_revoked(user_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(core_deps, "sessions_revoked_after", _never_revoked)


class _TripwireSession:
    """A session stand-in that explodes the moment anyone runs a query.

    Repositories capture the session in ``__init__`` without touching it, and
    FastAPI builds the *whole* dependency graph before a guard can reject the
    request — so a test of the tenancy guard on a monitoring route legitimately
    constructs a dozen repositories it never uses. Failing at construction would
    make those tests impossible; failing on first use still catches the thing
    that actually matters.
    """

    def __getattr__(self, name: str) -> Any:
        """Refuse every session operation with an actionable message."""
        raise AssertionError(
            f"A component test executed {name!r} against the database. Override "
            "the module's repository dependencies with fakes, or move the test "
            "to tests/integration/."
        )


@pytest.fixture(autouse=True)
def _no_database(app: FastAPI) -> Iterator[None]:
    """Ensure no component test can reach a real database.

    A component test that quietly opens a Postgres connection is an integration
    test wearing the wrong hat: it will be slow, order-dependent, and will pass
    on a laptop with docker running while failing in a unit-only CI stage.
    """

    def _tripwire() -> _TripwireSession:
        return _TripwireSession()

    app.dependency_overrides[get_db] = _tripwire
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def override(app: FastAPI) -> Iterator[Callable[[Any, Any], None]]:
    """Yield a helper that installs a dependency override for one test.

    Overrides are removed afterwards so the session-scoped app never carries
    one test's fakes into the next.

    Yields:
        ``override(dependency, replacement)`` — ``replacement`` is wrapped in a
        zero-argument callable when a plain object is passed.
    """
    installed: list[Any] = []

    def _install(dependency: Any, replacement: Any) -> None:
        provider = replacement if callable(replacement) else (lambda: replacement)
        app.dependency_overrides[dependency] = provider
        installed.append(dependency)

    yield _install

    for dependency in installed:
        app.dependency_overrides.pop(dependency, None)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx client speaking directly to the app over ASGI.

    ``ASGITransport`` runs the real middleware stack and exception handlers
    in-process — no socket, no uvicorn, no port.

    The base URL is **https** on purpose, and it is not cosmetic. The refresh
    cookie ships with ``Secure`` (``REFRESH_COOKIE_SECURE`` defaults to true,
    and production must never turn it off), and an HTTP client correctly
    refuses to return a ``Secure`` cookie over plain http. Over ``http://`` the
    rotation and logout tests therefore passed or failed according to whatever
    the developer's ``backend/.env`` happened to set — green locally, red on
    CI, which has no ``.env`` at all. Speaking https makes the tier hermetic
    (the cookie flows under either value) and matches how the app is really
    reached: behind nginx, over TLS.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as ac:
        yield ac


# --------------------------------------------------------------------------- #
# Common principals and tenancy
# --------------------------------------------------------------------------- #
@pytest.fixture
def user() -> User:
    """A regular, active user account."""
    return make_user(email="user@example.com")


@pytest.fixture
def dev_user() -> User:
    """A user holding the ``dev`` role (workspace administration)."""
    return make_user(email="dev@example.com", role=ROLE_DEV)


@pytest.fixture
def organization_id() -> uuid.UUID:
    """The tenant every fixture in this tier belongs to.

    One organisation, shared by the caller and the workspaces, because that is
    the ordinary case every route is written for. A test proving tenancy uses a
    SECOND id (see ``foreign_organization_id``) and asserts the request is
    refused — which only means anything because the default case is wired to
    succeed.
    """
    return uuid.UUID("018f4e2a-0000-7000-8000-0000000000aa")


@pytest.fixture
def foreign_organization_id() -> uuid.UUID:
    """Another tenant's id, for proving a request is scoped and not merely valid."""
    return uuid.UUID("018f4e2a-0000-7000-8000-0000000000bb")


@pytest.fixture
def workspace(organization_id: uuid.UUID) -> Workspace:
    """A non-primary workspace (stores a single ``unified`` WB token)."""
    return make_workspace(organization_id=organization_id, name="ИП Тестовый")


@pytest.fixture
def primary_workspace(organization_id: uuid.UUID) -> Workspace:
    """The primary workspace (stores one token per WB category)."""
    return make_workspace(organization_id=organization_id, name="ИП Демо", is_primary=True)


@pytest.fixture
def user_repo(user: User, dev_user: User) -> FakeUserRepository:
    """A user store seeded with both the regular and the dev principal."""
    return FakeUserRepository([user, dev_user])


@pytest.fixture
def token_repo() -> FakeRefreshTokenRepository:
    """An empty refresh-token store."""
    return FakeRefreshTokenRepository()


@pytest.fixture
def workspace_repo(workspace: Workspace, primary_workspace: Workspace) -> FakeWorkspaceRepository:
    """A workspace store seeded with one primary and one regular workspace."""
    return FakeWorkspaceRepository([primary_workspace, workspace])


@pytest.fixture
def workspace_token_repo() -> FakeWorkspaceTokenRepository:
    """An empty (ciphertext-only) workspace-token store."""
    return FakeWorkspaceTokenRepository()


@pytest.fixture
def authenticated(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
) -> None:
    """Wire the identity + tenancy dependencies every guarded route needs.

    Installs the fake user repository (so ``CurrentUser`` resolves without a
    database) and the fake workspace repository (so the ``X-Workspace-Id``
    header validates). Tests still send real signed tokens and a real header —
    the guards themselves are never stubbed.
    """
    from src.modules.users.deps import get_user_repo
    from src.modules.workspaces.deps import get_workspace_repo

    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)


@pytest.fixture
def access_factory(user: User, organization_id: uuid.UUID) -> Callable[..., OrganizationAccess]:
    """Build an :class:`OrganizationAccess` with the parts a test cares about.

    Every guard in the application resolves through ``get_current_access``, so
    overriding that ONE dependency with one of these decides what the caller may
    do — role, subscription state and internal-feature access all at once.
    """

    def _build(
        *,
        role: EffectiveRole = EffectiveRole.OWNER,
        subscription: SubscriptionState = SubscriptionState.ACTIVE,
        is_primary_org: bool = False,
        org: uuid.UUID | None = organization_id,
    ) -> OrganizationAccess:
        return OrganizationAccess(
            user_id=user.id,
            organization_id=org,
            role=role,
            subscription=subscription,
            is_primary_org=is_primary_org,
        )

    return _build


@pytest.fixture
def login_as(
    override: Callable[[Any, Any], None],
    access_factory: Callable[..., OrganizationAccess],
) -> Callable[..., None]:
    """Decide who the caller is for the rest of the test.

    ``login_as(role=..., subscription=..., is_primary_org=..., org=...)``
    replaces the ONE dependency every guard resolves through, so a single call
    decides what the request may do — no per-guard stubbing.

    The replacement still depends on ``CurrentUser``, and that is load-bearing:
    without it the override would short-circuit AUTHENTICATION too, and every
    "a bad token is a 401" test would quietly start asserting against a request
    that was never authenticated at all. Keeping the dependency means the token
    is still parsed, verified and resolved to a live account exactly as in
    production — only the membership lookup behind it is replaced.
    """

    def _apply(**kwargs: Any) -> None:
        fixed = access_factory(**kwargs)

        async def _provider(user: User = Depends(get_current_user)) -> OrganizationAccess:
            return replace(fixed, user_id=user.id)

        override(get_current_access, _provider)

    return _apply


@pytest.fixture(autouse=True)
def _wire_access(login_as: Callable[..., None]) -> None:
    """Default every request in this tier to an owner of the shared organisation.

    Autouse because the alternative is every one of ~200 route tests declaring
    the same fixture to test something else entirely. A test about a guard calls
    ``login_as(...)`` again with what it actually wants, and the last override
    wins.
    """
    login_as()
