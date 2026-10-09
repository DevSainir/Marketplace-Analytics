"""An abandoned read stops in PostgreSQL, and its connection comes back.

The unit tests show the middleware cancels the handler. Whether that reaches the
database is a different question, and the answer depended on WHERE the
middleware sits. Outermost — the first thing tried — the cancellation crossed
the request logger's anyio cancel scope, was re-delivered at every ``await``
SQLAlchemy needed to hand the connection back, the pool logged "Exception
terminating connection", and the statement ran on to its end. Innermost, asyncio
cancels once and asyncpg sends PostgreSQL a cancel request (measured
2026-10-09). So this serves ``main.app`` itself — its own middleware, in its own order — on
a real uvicorn and a real Postgres, with one route added for the duration:
moving the middleware back out fails it.
"""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import sqlalchemy as sa
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from main import app as production_app
from src.core import deps
from src.core.deps import DbSession
from tests.integration.conftest import TEST_DB_NAME, _dsn

pytestmark = pytest.mark.integration


@pytest.fixture
async def pooled_engine(
    postgres_ready: bool, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    """The app's session factory, on a POOLED engine — leaking is a pool's failure."""
    engine = create_async_engine(_dsn(TEST_DB_NAME), pool_size=2, max_overflow=0)
    monkeypatch.setattr(
        deps, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False)
    )
    yield engine
    await engine.dispose()


async def _running(engine: AsyncEngine, marker: str) -> int:
    """How many backends are still executing the marked statement."""
    async with engine.connect() as conn:
        return int(
            await conn.scalar(
                sa.text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE state = 'active' AND query LIKE :marker AND pid <> pg_backend_pid()"
                ),
                {"marker": f"%{marker}%"},
            )
            or 0
        )


async def test_a_read_the_client_abandoned_stops_in_postgres(pooled_engine: AsyncEngine) -> None:
    """The browser aborts after 0.3 s; the 30 s statement behind it is gone at once."""
    marker = f"abandoned-{uuid.uuid4().hex}"

    async def slow(session: DbSession) -> dict[str, bool]:
        await session.execute(sa.text(f"SELECT pg_sleep(30) /* {marker} */"))
        return {"finished": True}

    production_app.add_api_route("/__test__/slow", slow)
    route = production_app.router.routes[-1]
    # Listening before uvicorn starts: the client's connection waits in the
    # backlog instead of racing the server's startup.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            production_app, lifespan="off", log_level="error", timeout_graceful_shutdown=1
        )
    )
    serving = asyncio.ensure_future(server.serve(sockets=[listener]))
    try:
        async with httpx.AsyncClient() as client:
            with pytest.raises(httpx.TimeoutException):
                await client.get(f"http://127.0.0.1:{port}/__test__/slow", timeout=0.3)

        still_running = 1
        for _ in range(20):
            await asyncio.sleep(0.05)
            still_running = await _running(pooled_engine, marker)
            if not still_running:
                break
        await asyncio.sleep(0.1)
        checked_out = pooled_engine.pool.checkedout()  # type: ignore[attr-defined]
    finally:
        server.should_exit = True
        await serving
        production_app.router.routes.remove(route)

    assert still_running == 0
    assert checked_out == 0
