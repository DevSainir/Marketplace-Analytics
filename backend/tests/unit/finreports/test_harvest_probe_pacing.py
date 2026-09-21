"""When the gate declines to ASK, and what it says while declining.

Split from ``test_harvest_freshness_gate.py`` because the subject is different.
That file is about the gate's arithmetic — which window to ask about, and what
each answer from WB means. This one is about the three reasons the gate sends
nothing at all even though a report is outstanding, which are not answers from
WB and must not be recorded as if they were.

* **A standing penalty block.** The one place this gate fails closed. Until
  2026-09-19 the probe went out into the block, was refused, and was read as
  «we learned nothing, harvest anyway» — so a blocked endpoint drew a probe
  AND a walk on every tick, and WB answers a request inside an open block by
  restarting it longer. That is how 28 197 s became 302 940 s in three steps.
* **The cadence.** A period stays outstanding until its report is held, which
  is what makes a report WB serves eight days late reachable at all; unpaced
  it would cost 168 requests against a budget of about 94 a day.
* **Neither, for «Обновить».** The button is exempt from the clock and from
  nothing else.

The ordering between the first two is itself under test: the block is checked
first, so a seller reads «ВБ ограничил доступ» at every tick of a four-day
block rather than four times a day with silence in between.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.finreports.services.freshness_record import FreshnessOutcome
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.freshness import check_freshness
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

TODAY = date(2026, 8, 4)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace bundle with a usable statistics token."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(),
        name="Демо",
        statistics="a-statistics-token",
    )


class _FakeFinanceClient:
    """Records every window it is asked about, so «asked nothing» is checkable."""

    def __init__(self, row: object = None) -> None:
        self.row = row
        self.windows: list[tuple[date, date]] = []

    def __call__(self, *_args: object, **_kwargs: object) -> _FakeFinanceClient:
        return self

    async def __aenter__(self) -> _FakeFinanceClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def fetch_first_row(self, *, date_from: date, date_to: date) -> object:
        self.windows.append((date_from, date_to))
        return self.row


async def test_a_standing_block_stops_the_tick_before_anything_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one place this gate fails closed, and the reason it must.

    Until 2026-09-19 the probe went out first and its 429 was read as «we
    learned nothing, harvest anyway», so a blocked endpoint drew a probe AND a
    walk on every tick. WB answers a request made inside an open block by
    restarting the block longer: measured on «Демо», 28 197 s became
    18 624 s became 302 940 s — nine hours to a hundred and five — in three
    steps over 2026-09-17.

    A block is not an unanswered question. It is an answer.
    """
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 7, 26),
        held_ends=[],
        today=TODAY,
        blocked_for=34_801.0,
    )

    assert verdict.outcome is FreshnessOutcome.RATE_BLOCKED
    assert verdict.should_harvest is False
    assert fake.windows == [], "a blocked endpoint must not be probed"


async def test_a_workspace_with_nothing_outstanding_is_not_reported_as_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order matters: «done» outranks «blocked».

    A seller holding every report WB has formed is not waiting on anything, and
    saying «ВБ ограничил доступ» on their P&L would be alarming about a
    limiter that is costing them nothing. The block only means something once
    there is a request we would otherwise have sent.
    """
    fake = _FakeFinanceClient()
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 8, 2),
        held_ends=[date(2026, 8, 2)],
        today=TODAY,
        blocked_for=34_801.0,
    )

    assert verdict.outcome is FreshnessOutcome.UP_TO_DATE


async def test_a_paced_out_tick_records_nothing_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tick that did not ask must not overwrite the verdict of one that did.

    ``None``, not ``UP_TO_DATE``. The cadence exists so a report WB is days
    late does not cost 21 requests a day, but a paced-out tick has learned
    nothing — and writing «загружены по вчерашний день» over a week WB has
    published is the exact bug this module was rewritten to stop telling. The
    previous verdict stands and its `checked_at` ages honestly, which is what
    the page reads staleness from.

    04:00 MSK, against a period three days overdue: outside every band.
    """
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 7, 26),
        held_ends=[],
        today=TODAY,
        hour_msk=4,
    )

    assert verdict is None
    assert fake.windows == []


async def test_the_button_reaches_wb_whatever_the_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """«Обновить» is not paced, and that is the point of it.

    A button that quietly did nothing because the clock said 04:00 would be
    worse than no button — this one exists precisely for the case where
    waiting for the next scheduled tick is not the answer. The nightly
    reconciliation pass arrives the same way and is exempt for the same
    reason: a safety net that catches at three preset hours is not much of a
    net.
    """
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 7, 26),
        held_ends=[],
        today=TODAY,
        hour_msk=4,
        paced=False,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.WB_EMPTY
    assert fake.windows == [(date(2026, 7, 27), date(2026, 8, 2))]


async def test_a_block_stops_the_button_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one thing «Обновить» may not override.

    Unpaced means «the clock does not stop you». A penalty block is not the
    clock — WB has refused, and a request inside an open block restarts it
    longer, so pressing the button harder is the single action that makes the
    seller's report arrive later rather than sooner.
    """
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 7, 26),
        held_ends=[],
        today=TODAY,
        hour_msk=4,
        paced=False,
        blocked_for=34_801.0,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.RATE_BLOCKED
    assert fake.windows == []


async def test_a_block_is_reported_at_every_tick_not_only_at_probe_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """During a long block the page must keep saying so, hour after hour.

    The block check runs ahead of the cadence, and both are free, so the
    ordering costs nothing and decides only what the seller reads. Behind the
    cadence a four-day block would produce a verdict four hours a day and
    silence in between — and silence ages into «неизвестно, когда мы
    спрашивали», which is what a dead harvester looks like. «Демо» spent
    2026-09-19 to 2026-09-23 in exactly that state.

    04:00 MSK against a period three days overdue is outside every band.
    """
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(),
        latest_settled=date(2026, 7, 26),
        held_ends=[],
        today=TODAY,
        hour_msk=4,
        blocked_for=34_801.0,
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.RATE_BLOCKED
    assert fake.windows == []
