"""Fixtures for the pytest half of the performance tier.

Deliberately self-contained rather than importing the backend's integration
harness. These tests are about **resource exhaustion**, so they need engines and
pools they own and can deliberately starve — a shared, transaction-wrapped
session would hide the very behaviour under test.

Every fixture skips rather than fails when the infrastructure is missing, so
``pytest`` on a laptop without docker still exits 0.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

#: The backend's environment file. This tier runs from the repository root, so
#: pydantic-settings — which resolves ``env_file`` relative to the working
#: directory — would never find it and would silently fall back to the
#: Docker-internal hostnames (``postgres``, ``redis``), producing a confusing
#: DNS error instead of a connection.
_BACKEND_ENV = Path(__file__).resolve().parents[2] / "backend" / ".env"


def _load_backend_env() -> None:
    """Copy ``backend/.env`` into the process environment, without overriding.

    Values already present in the environment win, so CI can point this tier at
    a different database without editing any file.
    """
    if not _BACKEND_ENV.is_file():
        return
    for line in _BACKEND_ENV.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        # Trailing inline comments are used in this file (`localhost   # note`).
        cleaned = value.split("#", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key.strip(), cleaned)


_load_backend_env()

pytestmark = pytest.mark.performance

#: The database these probes run against. Defaults to the integration tier's
#: throwaway database — never the dev database, since a pool-exhaustion test
#: deliberately holds every connection it can get.
TEST_DB_NAME: str = os.getenv("TEST_POSTGRES_DB", "marketplace_test")


def _dsn(database: str) -> str:
    """Build an asyncpg DSN for a database on the configured Postgres host."""
    from src.core.config import settings

    return settings.database_url.rsplit("/", 1)[0] + f"/{database}"


@pytest.fixture(scope="session")
def database_url() -> str:
    """Return the DSN of the performance database, skipping if unreachable.

    Returns:
        The asyncpg DSN every engine in this tier is built from.
    """
    url = _dsn(TEST_DB_NAME)

    async def _probe() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_probe())
    except Exception as exc:
        pytest.skip(
            f"PostgreSQL database '{TEST_DB_NAME}' is unreachable "
            f"({type(exc).__name__}). Run the integration tier once to create it, "
            "or start docker: `docker compose up -d postgres`.",
            allow_module_level=True,
        )
    return url


@pytest.fixture
async def small_pool_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """An engine with a deliberately tiny pool, for saturation probes.

    Two connections and no overflow makes exhaustion reachable in a test
    instead of requiring the production pool's thirty.
    """
    engine = create_async_engine(
        database_url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=2,
        pool_pre_ping=True,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def observer_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """A separate, unpooled engine used to observe the server's own view.

    Reading ``pg_stat_activity`` through the pool being tested would consume the
    very connection the test is trying to prove is stuck.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """Return the base URL of a running API, skipping when none is up.

    Returns:
        The API origin the HTTP-level probes target.
    """
    import urllib.error
    import urllib.request

    url = os.getenv("PERF_API_URL", "http://localhost:8000")
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=2) as response:  # noqa: S310
            if response.status != 200:
                raise RuntimeError(f"health returned {response.status}")
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        pytest.skip(
            f"No API answering at {url} ({exc}). Start the stack with "
            "`docker compose up -d` or set PERF_API_URL.",
            allow_module_level=True,
        )
    return url
