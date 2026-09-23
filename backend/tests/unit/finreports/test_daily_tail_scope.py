"""«Обновить» fills the provisional tail, and only for the кабинет that asked.

Two properties, and each was a bug before it was a rule.

**A click must reach the tail at all.** The days it covers — between the last
weekly report and yesterday — are usually the days somebody is looking at when
they press the button, and before this they arrived only on the next hourly
tick, up to an hour later.

**A click must not spend anyone else's WB budget.** The same rule the settled
harvest's route already follows: it used to enqueue the fleet walk, so one
seller's button spent every other seller's rate budget and held the shared lock
for the length of a platform-wide run. A scoped run also takes a lock of its own
rather than the harvest's — under the shared one the click would answer
«already running» and fetch nothing exactly while the hourly sweep was in
flight, which is the case the button exists for.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest

from src.modules.finreports.constants import DAILY_TAIL_LOCK_PREFIX, HARVEST_LOCK_KEY
from src.modules.finreports.tasks import daily_tail
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

MINE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
THEIRS = uuid.UUID("01a07a8d-6e3e-7012-ab9f-34443d93776d")
TODAY = date(2026, 9, 23)


@dataclass
class _Run:
    """What one lane run did, as seen from outside the process.

    Attributes:
        walked: The workspaces actually harvested, in order.
        locks: The Redis keys the run took — a scoped run must not take the
            fleet's.
        fleet_loaded: Non-empty when the fleet credential loader was called,
            which decrypts every tenant's WB tokens.
    """

    walked: list[uuid.UUID] = field(default_factory=list)
    locks: list[str] = field(default_factory=list)
    fleet_loaded: list[bool] = field(default_factory=list)


class _FakeSession:
    """A session that is opened and closed and never queried."""

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _bundle(workspace_id: uuid.UUID, name: str) -> WorkspaceTokenBundle:
    """A workspace with the «Финансы» token the lane requires."""
    return WorkspaceTokenBundle(workspace_id=workspace_id, name=name, finance="a-finance-token")


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch):
    """Drive the lane with its WB work and its credential loading replaced.

    What the tests read is which workspaces were walked and which lock was
    taken — the two things a scoped run has to get right, and both invisible in
    the return value.
    """
    run = _Run()

    async def _tail_one(*, tokens: WorkspaceTokenBundle, today: date) -> dict[str, int]:
        run.walked.append(tokens.workspace_id)
        return dict(daily_tail._EMPTY, reports=1)

    async def _fleet(*_args: object, **_kwargs: object) -> list[WorkspaceTokenBundle]:
        run.fleet_loaded.append(True)
        return [_bundle(MINE, "Демо"), _bundle(THEIRS, "NEVA")]

    async def _one(_session: object, workspace_id: uuid.UUID) -> WorkspaceTokenBundle | None:
        return _bundle(workspace_id, "Демо") if workspace_id == MINE else None

    class _Flight:
        def __init__(self, key: str, **_kwargs: object) -> None:
            run.locks.append(key)

        async def __aenter__(self) -> bool:
            return True

        async def __aexit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(daily_tail, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(daily_tail, "single_flight", _Flight)
    monkeypatch.setattr(daily_tail, "get_redis", lambda: None)
    monkeypatch.setattr(daily_tail, "moscow_today", lambda: TODAY)
    monkeypatch.setattr(daily_tail, "_tail_one_workspace", _tail_one)
    monkeypatch.setattr(daily_tail, "load_workspace_token_bundles", _fleet)
    monkeypatch.setattr(daily_tail, "load_workspace_token_bundle", _one)

    return run


async def test_a_scoped_run_walks_only_the_workspace_that_asked(run) -> None:
    """One tenant's click must not spend another tenant's WB budget."""
    await daily_tail.harvest_daily_tail(workspace_id=MINE)

    assert run.walked == [MINE]


async def test_a_scoped_run_does_not_decrypt_every_tenants_tokens(run) -> None:
    """The fleet loader decrypts every workspace's WB secrets.

    Loading them all and filtering would reach every tenant's credentials to
    answer one tenant's click — see `_bundles_to_tail`.
    """
    await daily_tail.harvest_daily_tail(workspace_id=MINE)

    assert run.fleet_loaded == []


async def test_a_scoped_run_takes_its_own_lock_not_the_harvests(run) -> None:
    """Under the shared lock the button fetches nothing while the sweep runs.

    That is the one case «Обновить» exists for, so the scoped run is keyed on
    the workspace: it still cannot walk the same кабинет twice at once, and it
    no longer waits on a sweep of everybody else's.
    """
    await daily_tail.harvest_daily_tail(workspace_id=MINE)

    assert run.locks == [f"{DAILY_TAIL_LOCK_PREFIX}{MINE}"]
    assert HARVEST_LOCK_KEY not in run.locks


async def test_the_fleet_sweep_still_takes_the_shared_lock(run) -> None:
    """Two sweeps at once would queue on the same WB buckets for minutes."""
    await daily_tail.harvest_daily_tail()

    assert run.locks == [HARVEST_LOCK_KEY]
    assert run.walked == [MINE, THEIRS]


async def test_a_scoped_run_for_a_workspace_that_is_gone_walks_nothing(run) -> None:
    """A deleted кабинет is not an error, and must not fall back to the fleet."""
    await daily_tail.harvest_daily_tail(workspace_id=THEIRS)

    assert run.walked == []
