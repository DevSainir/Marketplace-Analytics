"""The post-harvest warm-up of the settlement rollup.

The rollup repairs itself on read, so warming it can never change a figure —
only who pays for the repair. What can go wrong is the WINDOW: warm the last
four weeks and «Вся история» is still a cold 17 s rebuild in front of a user,
which is the timeout this whole mechanism exists to remove. That is what these
pin.

Unit tier: the seam is the two collaborators, and both are faked.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.tasks import warmup as warmup_module

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000beef")

#: Report headers as the repository returns them: (report_id, from, to),
#: deliberately out of order — WB serves back-dated weeks late.
PERIODS = [
    (785_000_000, date(2026, 7, 6), date(2026, 7, 12)),
    (785_841_585, date(2026, 7, 13), date(2026, 7, 19)),
    (784_000_000, date(2024, 1, 29), date(2024, 2, 4)),
]


class _FakeSession:
    """An async context manager standing in for a real session."""

    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _FakeReports:
    """Only the one method the warm-up calls."""

    def __init__(self, periods: list[tuple[int, date, date]]) -> None:
        self._periods = periods

    async def list_periods(self, *, workspace_id: uuid.UUID) -> list[tuple[int, date, date]]:
        return self._periods


@pytest.fixture
def warmed(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Record the window the warm-up asks the rollup to make fresh."""
    asked: dict[str, object] = {}
    session = _FakeSession()

    class _FakeRollup:
        def __init__(self, _session: object) -> None:
            pass

        async def ensure_fresh(
            self, *, workspace_id: uuid.UUID, date_from: date, date_to: date
        ) -> int:
            asked.update(workspace_id=workspace_id, date_from=date_from, date_to=date_to)
            return 3

    monkeypatch.setattr(warmup_module, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(warmup_module, "SettlementRollup", _FakeRollup)
    asked["session"] = session
    return asked


async def test_the_warm_up_covers_everything_wb_has_ever_settled(
    monkeypatch: pytest.MonkeyPatch, warmed: dict[str, object]
) -> None:
    """The window is the full span of the report headers, not the newest week.

    Warming a short window would leave the one read this exists for — «Вся
    история» — exactly as cold as before, and nothing would look broken.
    """
    monkeypatch.setattr(
        warmup_module, "FinancialReportRepository", lambda _s: _FakeReports(PERIODS)
    )

    await warmup_module.warm_settlement_rollup(workspace_id=WORKSPACE, name="Демо")

    assert warmed["date_from"] == date(2024, 1, 29)
    assert warmed["date_to"] == date(2026, 7, 19)


async def test_a_кабинет_with_no_reports_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, warmed: dict[str, object]
) -> None:
    """Nothing settled means nothing to summarise — and no empty rebuild."""
    monkeypatch.setattr(warmup_module, "FinancialReportRepository", lambda _s: _FakeReports([]))

    await warmup_module.warm_settlement_rollup(workspace_id=WORKSPACE, name="Новый")

    assert "date_from" not in warmed


async def test_a_failed_warm_up_does_not_reach_the_harvest(
    monkeypatch: pytest.MonkeyPatch, warmed: dict[str, object]
) -> None:
    """A broken warm-up is a slow page, never a lost settlement.

    It runs after the harvest has committed, so raising here would turn a
    successful harvest into a failed task and a retry that re-downloads WB's
    whole week.
    """

    def _explode(_session: object) -> _FakeReports:
        raise RuntimeError("no connection")

    monkeypatch.setattr(warmup_module, "FinancialReportRepository", _explode)

    await warmup_module.warm_settlement_rollup(workspace_id=WORKSPACE, name="Демо")


async def test_the_warm_up_commits_what_it_built(
    monkeypatch: pytest.MonkeyPatch, warmed: dict[str, object]
) -> None:
    """Without the commit the rebuild is rolled back and nobody is any faster.

    The read path fills the same table inside the request's own transaction, so
    an uncommitted warm-up looks identical from here and is worth nothing —
    which is exactly how this would ship unnoticed.
    """
    monkeypatch.setattr(
        warmup_module, "FinancialReportRepository", lambda _s: _FakeReports(PERIODS)
    )

    await warmup_module.warm_settlement_rollup(workspace_id=WORKSPACE, name="Демо")

    session = warmed["session"]
    assert isinstance(session, _FakeSession)
    assert session.committed
