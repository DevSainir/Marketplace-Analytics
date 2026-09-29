"""A database that cannot be read costs the crash signal one stale sample, not the scrape."""

from __future__ import annotations

from typing import Any

import pytest
from prometheus_client import REGISTRY

from src.core.observability import collectors
from src.core.observability.metrics import POSTGRES_STATS_RESET

pytestmark = pytest.mark.unit


class _UnreachableEngine:
    """An engine whose every connection attempt is refused."""

    def connect(self) -> Any:
        raise OSError("connection refused")


async def test_an_unreachable_database_leaves_the_last_value_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sample is skipped; the gauge keeps what it had.

    Exactly when Postgres is down is when the rest of the scrape matters most —
    a sampler that raised would take ``dependency_up`` down with it.
    """
    POSTGRES_STATS_RESET.set(1_790_000_000.0)
    monkeypatch.setattr(collectors, "engine", _UnreachableEngine())

    await collectors.sample_postgres_stats_reset()

    assert REGISTRY.get_sample_value("postgres_stats_reset_timestamp_seconds") == 1_790_000_000.0
