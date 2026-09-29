"""The scrape publishes the moment PostgreSQL last recovered from a crash.

On 2026-09-29 the postgres container's OOM killer took a backend, the server
reinitialised, and two seconds later it was accepting connections again —
inside one 15 s scrape, so ``dependency_up`` never went to 0. The one trace that
outlasts a recovery is ``pg_stat_bgwriter.stats_reset``, which PostgreSQL moves
only when it discards statistics after a crash. ``PostgresCrashRecovered`` in
``alerts.yml`` fires when this gauge changes.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY

from src.core.observability.collectors import sample_postgres_stats_reset

pytestmark = pytest.mark.usefixtures("postgres_ready")


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> Any:
    """Drain the process-wide pool around the test, as ``test_readiness_probe`` does.

    The sampler takes its connection from the shared engine, and asyncpg binds a
    pooled connection to the loop that opened it; each test gets a new loop.
    """
    from src.core.database import dispose_engine

    await dispose_engine()
    yield
    await dispose_engine()


async def test_the_gauge_carries_the_servers_own_recovery_time() -> None:
    """The published value is PostgreSQL's ``stats_reset``, to the second."""
    from src.core.database import engine

    async with engine.connect() as connection:
        expected = float(
            await connection.scalar(
                sa.text("SELECT extract(epoch FROM stats_reset) FROM pg_stat_bgwriter")
            )
        )

    await sample_postgres_stats_reset()

    assert REGISTRY.get_sample_value("postgres_stats_reset_timestamp_seconds") == expected
