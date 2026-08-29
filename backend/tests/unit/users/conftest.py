"""Keep the unit tier's rotation tests off Redis.

Rotation now consults the replay-grace store (register P0.5), which is Redis. A
unit test must not touch it — the tier's whole value is that it runs anywhere,
in any order, with nothing running — and a test that quietly reached a live
Redis would also inherit whatever the previous test left in it.

Zero is the documented "no grace" setting rather than a test-only switch, so
what these tests exercise is real strict-rotation behaviour: every replay is a
breach. The grace path is covered where it can be covered honestly, against a
real Redis, in ``tests/integration/users/test_concurrent_tab_refresh.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_replay_grace(settings_override: Any) -> Iterator[None]:
    """Disable the grace window so rotation stays a pure, in-memory operation."""
    with settings_override(refresh_replay_grace_seconds=0):
        yield
