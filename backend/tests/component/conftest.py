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
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.core import ratelimit
from src.core.deps import get_db
from src.modules.users.models import ROLE_DEV, User
from src.modules.workspaces.models import Workspace
from tests.support.auth import make_user
from tests.support.fakes import (
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


class _InMemoryRedis:
    """The four commands this tier's Redis callers actually use.

    Backing them with dicts keeps the *real* caller in the request path — the
    limiter's counter key, budget comparison and 429; the refresh tracker's
    ownership key and its comparison — while needing no Redis server. Replacing
    those callers with stubs would have hidden a whole dependency from every
    component test, and (worse) stopped exercising the logic under test.

    Note the ``str`` values: the shared client runs with
    ``decode_responses=True``, so a real ``get`` returns ``str``, not ``bytes``.
    """

    def __init__(self) -> None:
        """Start with empty tables."""
        self.counters: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.values: dict[str, str] = {}

    async def incr(self, key: str) -> int:
        """Increment and return a counter, creating it at 1."""
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> bool:
        """Record the window length (never actually elapses within a test)."""
        self.expiries[key] = seconds
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        """Store a value, recording any TTL (which never elapses in a test)."""
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        """Return a stored value, or ``None`` when the key is absent."""
        return self.values.get(key)


@pytest.fixture(autouse=True)
def rate_limiter_store(monkeypatch: pytest.MonkeyPatch) -> _InMemoryRedis:
    """Back the rate limiter with a per-test in-memory counter store.

    Each test starts with a clean budget, so one test's login attempts can never
    throttle the next. Behaviour against a *real* Redis (shared counters across
    replicas, window expiry, fail-open on outage) is covered in
    ``tests/integration/core/test_rate_limiting.py``.

    Returns:
        The store, so a test can inspect or pre-load the counters.
    """
    store = _InMemoryRedis()
    monkeypatch.setattr(ratelimit, "get_redis", lambda: store)
    return store


@pytest.fixture(autouse=True)
def refresh_task_store(monkeypatch: pytest.MonkeyPatch) -> _InMemoryRedis:
    """Back the «Обновить» task-ownership binding with an in-memory store.

    ``refresh_tracking`` records which workspace enqueued a refresh task so the
    status endpoint can refuse another tenant's task id. Without this the tier
    would reach for a real Redis — which the `fast` CI job does not run — and
    the guard would be untestable here at all.

    Returns:
        The store, so a test can inspect the recorded bindings.
    """
    from src.modules.monitoring.services import refresh_tracking

    store = _InMemoryRedis()
    monkeypatch.setattr(refresh_tracking, "get_redis", lambda: store)
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
def workspace() -> Workspace:
    """A non-primary workspace (stores a single ``unified`` WB token)."""
    return make_workspace(name="ИП Тестовый")


@pytest.fixture
def primary_workspace() -> Workspace:
    """The primary workspace (stores one token per WB category)."""
    return make_workspace(name="ИП Демо", is_primary=True)


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
