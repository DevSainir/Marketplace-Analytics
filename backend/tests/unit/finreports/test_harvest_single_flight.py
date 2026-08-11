"""The finance harvest refuses to run alongside itself.

The schedule ticks hourly; a tick that finds a new report walks for minutes of
a lock — otherwise the 10:00 tick would join the 09:00 tick already in flight
and the two would spend each other's budget on a ~1 req/min surface, which is
how the storage claim ended up covering 70 of 910 days once before.

The turned-away tick must be *cheap and silent*: no WB call, no DB session, and
a result whose shape is the same as a real run's so nothing downstream has to
special-case it.
"""

from __future__ import annotations

import pytest

from src.modules.finreports.tasks import harvest
from src.modules.finreports.tasks.harvest import harvest_all_workspaces

pytestmark = pytest.mark.unit


class _HeldRedis:
    """A Redis whose lock key is already taken by another run."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {harvest._HARVEST_LOCK_KEY: "another-runs-token"}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def eval(self, script: str, numkeys: int, *args: str) -> int:
        key, token = args[0], args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


async def test_a_tick_that_finds_the_lock_held_does_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Arrange a held lock; the tick must return without loading a workspace.

    ``load_workspace_token_bundles`` is the harvest's first act and its first DB
    hit, so replacing it with a detonator proves the run stopped at the lock
    rather than somewhere later.
    """
    redis = _HeldRedis()
    monkeypatch.setattr(harvest, "get_redis", lambda: redis)

    async def _explode(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("the locked-out tick opened a session anyway")

    monkeypatch.setattr(harvest, "load_workspace_token_bundles", _explode)

    totals = await harvest_all_workspaces(days=28)

    assert totals["skipped_locked"] == 1
    assert totals["finance"] == 0


async def test_the_locked_out_result_has_the_same_shape_as_a_real_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers read these keys unconditionally; a missing one is an error."""
    monkeypatch.setattr(harvest, "get_redis", lambda: _HeldRedis())

    totals = await harvest_all_workspaces(days=28)

    assert set(totals) == set(harvest._EMPTY_TOTALS)


async def test_the_lock_is_freed_for_the_next_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed harvest must not leave the job blocked until the TTL."""
    redis = _HeldRedis()
    redis.store.clear()
    monkeypatch.setattr(harvest, "get_redis", lambda: redis)

    async def _no_workspaces(*args: object, **kwargs: object) -> list[object]:
        return []

    monkeypatch.setattr(harvest, "load_workspace_token_bundles", _no_workspaces)

    await harvest_all_workspaces(days=28)

    assert redis.store == {}
