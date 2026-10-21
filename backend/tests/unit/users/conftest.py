"""Keep this tier's auth tests off a real Redis.

Two Redis-backed controls now sit in paths these tests exercise, and a unit test
must touch neither — the tier's whole value is that it runs anywhere, in any
order, with nothing running, and a test that quietly reached a live Redis would
also inherit whatever the previous test left in it.

**Rotation** consults the replay-grace store. That one is
switched off rather than faked, because zero is the documented "no grace"
setting.

**Logout, revocation and login** consult the watermarks and the per-account
backoff. Those are faked, not switched off, because their
behaviour is the thing under test: :func:`redis_store` puts one in-memory store
behind ``get_redis`` for the whole tier, exactly as the component tier's fixture
of the same name does, so a test can assert on what was written.

What the rotation tests then exercise is real strict-rotation behaviour: every
replay is a breach. The grace path is covered where it can be covered honestly,
against a real Redis, in ``tests/integration/users/test_concurrent_tab_refresh.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests.support.fakes import FakeRedis


@pytest.fixture(autouse=True)
def _no_replay_grace(settings_override: Any) -> Iterator[None]:
    """Disable the grace window so rotation stays a pure, in-memory operation."""
    with settings_override(refresh_replay_grace_seconds=0):
        yield


@pytest.fixture(autouse=True)
def redis_store(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Back every Redis-backed control in this tier with one in-memory store.

    One fixture because there is one seam: every caller resolves the client
    through ``get_redis()``, which reads this module global at call time.

    Returns:
        The store, so a test can inspect what a revocation actually wrote.
    """
    from src.core import redis as core_redis

    store = FakeRedis()
    monkeypatch.setattr(core_redis, "_redis", store)
    return store
