"""The daily tail warms the P&L rollup after it changes rows, and only then.

The weekly walk warms after itself; the daily lane lands on its own most
mornings, and a day it writes or clears is stale in the rollup until something
rebuilds it. Left to the read path, that is the first seller to open the P&L.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.tasks.daily_tail import harvest as tail
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

BUNDLE = WorkspaceTokenBundle(
    workspace_id=uuid.UUID("019f657a-0000-7000-8000-00000000da11"),
    name="Демо",
    statistics="s",
    finance="f",
)
TODAY = date(2026, 9, 26)


def _wire(monkeypatch: pytest.MonkeyPatch, *, dropped: int, rows: int) -> list[uuid.UUID]:
    """A tail whose sweep drops ``dropped`` rows and whose fetch writes ``rows``."""
    warmed: list[uuid.UUID] = []

    async def _frontier(**_kwargs: object) -> date:
        return date(2026, 9, 20)

    async def _drop(**_kwargs: object) -> int:
        return dropped

    async def _fetch(**_kwargs: object) -> dict[str, int]:
        return dict(tail._EMPTY, rows=rows)

    async def _warm(*, workspace_id: uuid.UUID, name: str) -> None:
        warmed.append(workspace_id)

    monkeypatch.setattr(tail, "settled_frontier", _frontier)
    monkeypatch.setattr(tail, "_drop_closed_days", _drop)
    monkeypatch.setattr(tail, "_fetch_tail", _fetch)
    monkeypatch.setattr(tail, "warm_settlement_rollup", _warm)
    return warmed


async def test_landing_a_daily_report_warms_the_rollup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows written: the seller's rollup is rebuilt before anyone reads it."""
    warmed = _wire(monkeypatch, dropped=0, rows=12)

    await tail.tail_one_workspace(tokens=BUNDLE, today=TODAY)

    assert warmed == [BUNDLE.workspace_id]


async def test_clearing_a_closed_day_warms_the_rollup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows dropped with nothing fetched still leave days stale."""
    warmed = _wire(monkeypatch, dropped=3, rows=0)

    await tail.tail_one_workspace(tokens=BUNDLE, today=TODAY)

    assert warmed == [BUNDLE.workspace_id]


async def test_a_tail_that_changed_nothing_warms_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most ticks change nothing; a whole-history freshness check each is waste."""
    warmed = _wire(monkeypatch, dropped=0, rows=0)

    await tail.tail_one_workspace(tokens=BUNDLE, today=TODAY)

    assert warmed == []
