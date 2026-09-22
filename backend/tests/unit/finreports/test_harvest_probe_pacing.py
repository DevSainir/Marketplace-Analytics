"""When the gate declines to ASK, and what it says while declining.

Three reasons the gate sends nothing even though a report is outstanding.
None of them is an answer from WB, and none may be recorded as one.

* **A standing penalty block.** The one place this gate fails closed. Until
  2026-09-19 the request went out into the block, was refused, and was read as
  «we learned nothing, harvest anyway» — and WB answers a request inside an
  open block by restarting it longer.
* **The cadence.** A report stays outstanding until it is held, which is what
  makes one WB serves eight days late reachable at all; unpaced it would cost
  every tick of every one of those days.
* **Neither, for «Обновить».** The button is exempt from the clock and from
  nothing else.

The ORDER between the first two is under test: the block is checked first, so
a seller reads «ВБ ограничил доступ» at every tick of a long block rather than
four times a day with silence in between.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.modules.finreports.services.freshness_record import FreshnessOutcome
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.freshness import check_freshness
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 22)
#: Stamped four days ago, so the cadence is in its «three times a day» band.
OVERDUE_TO = date(2026, 9, 13)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace bundle with the «Финансы» token the report needs."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(), name="Демо", finance="a-finance-token"
    )


class _FakeClient:
    """A WB that always has one report we do not hold, and counts the asking."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: object, **_kwargs: object) -> _FakeClient:
        return self

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def list_reports(self, *, date_from: date, date_to: date) -> list[Any]:
        self.calls += 1
        from src.integrations.wildberries.schemas import WBFinanceReportHeader

        return [
            WBFinanceReportHeader.model_validate(
                {
                    "reportId": 902,
                    "dateFrom": (OVERDUE_TO - timedelta(days=6)).isoformat(),
                    "dateTo": OVERDUE_TO.isoformat(),
                    "createDate": (OVERDUE_TO + timedelta(days=1)).isoformat(),
                }
            )
        ]


@pytest.fixture
def wb(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Point the gate at a WB that always has something outstanding."""
    client = _FakeClient()
    monkeypatch.setattr(freshness, "WBFinanceReportsClient", client)
    return client


async def test_a_paced_out_tick_records_nothing_at_all(wb: _FakeClient) -> None:
    """A tick that did not ask must not overwrite the verdict of one that did.

    ``None``, not ``UP_TO_DATE``. Writing «загружены по вчерашний день» over a
    week WB has published is the exact bug this gate was rewritten to stop
    telling; the previous verdict stands and its `checked_at` ages honestly.
    """
    verdict, missing = await check_freshness(
        tokens=_tokens(), latest_settled=OVERDUE_TO, held=set(), today=TODAY, hour_msk=4
    )

    assert verdict is None
    assert missing == ()


async def test_the_button_reaches_wb_whatever_the_hour(wb: _FakeClient) -> None:
    """«Обновить» is not paced, and that is the point of it.

    A button that quietly did nothing because the clock said 04:00 would be
    worse than no button — it exists precisely for the case where waiting for
    the next scheduled tick is not the answer.
    """
    verdict, missing = await check_freshness(
        tokens=_tokens(),
        latest_settled=OVERDUE_TO,
        held=set(),
        today=TODAY,
        hour_msk=4,
        paced=False,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.WB_HAS_NEW
    assert [report.report_id for report in missing] == [902]


async def test_a_block_stops_the_button_too(wb: _FakeClient) -> None:
    """The one thing «Обновить» may not override.

    Unpaced means «the clock does not stop you». A penalty block is not the
    clock: WB has refused, and pressing harder is the single action that makes
    the seller's report arrive later rather than sooner.
    """
    verdict, missing = await check_freshness(
        tokens=_tokens(),
        latest_settled=OVERDUE_TO,
        held=set(),
        today=TODAY,
        hour_msk=4,
        paced=False,
        blocked_for=34_801.0,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.RATE_BLOCKED
    assert missing == ()
    assert wb.calls == 0, "a blocked endpoint must not be asked"


async def test_a_block_is_reported_at_every_tick_not_only_at_probe_hours(
    wb: _FakeClient,
) -> None:
    """During a long block the page must keep saying so, hour after hour.

    Both checks are free, so the ordering costs nothing and decides only what
    the seller reads. Behind the cadence a four-day block would produce a
    verdict three times a day and silence in between — and silence ages into
    «неизвестно, когда мы спрашивали», which is what a dead harvester looks
    like. «Демо» spent 2026-09-19 to 2026-09-23 in exactly that state.
    """
    verdict, _missing = await check_freshness(
        tokens=_tokens(),
        latest_settled=OVERDUE_TO,
        held=set(),
        today=TODAY,
        hour_msk=4,
        blocked_for=34_801.0,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.RATE_BLOCKED
    assert wb.calls == 0
