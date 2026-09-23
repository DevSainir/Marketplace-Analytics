"""«Обновить» fills the provisional tail, and only for the кабинет that asked.

Two properties, and each was a bug before it was a rule.

**A click must reach the tail at all.** The days it covers — between the last
weekly report and yesterday — are usually the days somebody is looking at when
they press the button, and before this they arrived only on the next scheduled
tick.

**A click must not spend anyone else's WB budget, or wait behind it.** The task
used to sweep the fleet, so one seller's button reached every tenant's tokens.
And it took the harvest's own lock, under which a click landing during the
scheduled sweep would answer «already running» and fetch nothing — exactly the
case the button exists for. It is now scoped to one workspace and keyed on it:
the lock only has to stop two clicks on the same кабинет walking it twice.

The fleet sweep is not tested here because it is no longer here — it runs inside
the settled harvest's tick, after each seller's weekly walk. See
`test_settlement_reconciliation.py` for that tick.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

import pytest

from src.modules.finreports.constants import DAILY_TAIL_LOCK_PREFIX, HARVEST_LOCK_KEY
from src.modules.finreports.tasks.daily_tail import harvest as daily_tail
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
    """

    walked: list[uuid.UUID] = field(default_factory=list)
    locks: list[str] = field(default_factory=list)


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
    monkeypatch.setattr(daily_tail, "tail_one_workspace", _tail_one)
    monkeypatch.setattr(daily_tail, "load_workspace_token_bundle", _one)

    return run


async def test_a_scoped_run_walks_only_the_workspace_that_asked(run) -> None:
    """One tenant's click must not spend another tenant's WB budget."""
    await daily_tail.harvest_daily_tail(workspace_id=MINE)

    assert run.walked == [MINE]


async def test_a_scoped_run_takes_its_own_lock_not_the_harvests(run) -> None:
    """Under the shared lock the button fetches nothing while the sweep runs.

    That is the one case «Обновить» exists for, so the scoped run is keyed on
    the workspace: it still cannot walk the same кабинет twice at once, and it
    no longer waits on a sweep of everybody else's.
    """
    await daily_tail.harvest_daily_tail(workspace_id=MINE)

    assert run.locks == [f"{DAILY_TAIL_LOCK_PREFIX}{MINE}"]
    assert HARVEST_LOCK_KEY not in run.locks


async def test_a_scoped_run_for_a_workspace_that_is_gone_walks_nothing(run) -> None:
    """A deleted кабинет is not an error, and must not fall back to the fleet."""
    await daily_tail.harvest_daily_tail(workspace_id=THEIRS)

    assert run.walked == []
