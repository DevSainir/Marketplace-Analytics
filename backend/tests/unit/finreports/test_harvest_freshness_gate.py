"""Unit tests for the freshness gate in front of the finreports harvest.

The gate decides whether a daily run walks WB at all, so its two ways of being
wrong are not symmetric. Skipping a harvest that should have run leaves a
settlement week out of the P&L silently — which is exactly what happened for
three days in August 2026 when the harvest task was crashing, and nothing in the
product could tell that apart from "WB published nothing". Running a harvest that
was not needed costs a few minutes of paced requests and nothing else.

So every case that is not a definite "WB has nothing new" must harvest, and the
tests below exist to keep it that way.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.modules.finreports.services.freshness_record import FreshnessOutcome
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.freshness import check_freshness, probe_window
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

TODAY = date(2026, 8, 4)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace bundle with a usable statistics token."""
    return WorkspaceTokenBundle(
        workspace_id=uuid.uuid4(),
        name="Демо",
        statistics="stat-token",
        analytics="analytics-token",
    )


def _client(handler: Any) -> WBFinanceClient:
    """Build a finance client whose transport is driven by ``handler``."""
    from src.core.config import settings

    client = WBFinanceClient(
        settings.model_copy(update={"wb_rate_pacing_enabled": False}), token="stat-token"
    )
    client._client = httpx.AsyncClient(
        base_url="https://wb.test",
        transport=httpx.MockTransport(handler),
    )
    return client


class _FakeFinanceClient:
    """Stands in for :class:`WBFinanceClient` inside the gate.

    Hand-written rather than a ``MagicMock`` so a renamed probe method fails the
    test instead of silently returning another mock and leaving the gate green.
    """

    def __init__(self, *, row: Any = None, error: Exception | None = None) -> None:
        self.row = row
        self.error = error
        self.windows: list[tuple[date, date]] = []

    def __call__(self, _settings: Any, *, token: str) -> _FakeFinanceClient:
        """Let one instance double as the class the gate constructs."""
        self.token = token
        return self

    async def __aenter__(self) -> _FakeFinanceClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def fetch_first_row(self, *, date_from: date, date_to: date) -> Any:
        self.windows.append((date_from, date_to))
        if self.error is not None:
            raise self.error
        return self.row


# --- probe_window ---------------------------------------------------------


def test_nothing_is_asked_about_a_period_wb_cannot_have_formed_yet() -> None:
    """The saving, and the whole reason the hourly probe could be retired.

    04.08.2026 is a Tuesday. The period 03.08-09.08 is still open, so its
    report cannot exist before 10.08 — and until 2026-09-19 the gate spent a
    settlement request asking about it anyway, twenty-one times a day, six days
    a week. There is nothing to ask.
    """
    window = probe_window(latest_settled=date(2026, 8, 2), held_ends=[], today=TODAY)

    assert window is None


def test_the_window_opens_at_the_oldest_period_wb_has_formed_but_we_lack() -> None:
    """Oldest, not newest, and the distinction is the 31.08 incident in miniature.

    Two periods are formed and unheld here — 27.07-31.07 (stamped 01.08) and
    01.08-02.08 (stamped 03.08). Starting at the newer one would ask WB a
    question the older report cannot answer, and the older report would then
    never be asked about again.
    """
    window = probe_window(latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY)

    assert window is not None
    assert (window.date_from, window.date_to) == (date(2026, 7, 27), date(2026, 8, 2))


def test_the_window_stops_at_the_last_period_wb_has_closed() -> None:
    """Not at yesterday, and the difference is a request per seller per cycle.

    04.08.2026 is a Tuesday: the period 03.08-09.08 is open and cannot have a
    report, so a window running to yesterday (03.08) reaches into it. Harmless
    for the probe, which is one request whatever its width — but the WALK is
    cut into weekly windows and pays for every one, and that one could only
    ever be answered 204.
    """
    window = probe_window(latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY)

    assert window is not None
    assert window.date_to == date(2026, 8, 2)
    assert window.date_to < TODAY - timedelta(days=1)


def test_a_report_held_out_of_order_does_not_close_the_window_behind_it() -> None:
    """Holding the newer report is not holding the older one.

    This is the failure that cost every workspace 31.08.2026: the 01.09-06.09
    report landed first, every forward-looking cursor jumped past 31.08, and
    the day became unreachable. Here the older period is still missing, so the
    window still opens on it.

    And closes on it: holding 01.08-02.08 takes that period out of the
    question, so the window is exactly the one period still owed rather than
    everything between them.
    """
    window = probe_window(
        latest_settled=date(2026, 7, 26), held_ends=[date(2026, 8, 2)], today=TODAY
    )

    assert window is not None
    assert (window.date_from, window.date_to) == (date(2026, 7, 27), date(2026, 7, 31))


def test_a_complete_history_yields_no_window() -> None:
    """Every formed period held: the gate answers without spending a request."""
    window = probe_window(
        latest_settled=date(2026, 8, 2), held_ends=[date(2026, 8, 2)], today=TODAY
    )

    assert window is None


# --- check_freshness ------------------------------------------------------


async def test_a_never_harvested_workspace_is_harvested_without_asking_wb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Everything WB holds is new, so the probe would only cost a request."""
    fake = _FakeFinanceClient()
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=None, held_ends=[], today=TODAY
    )

    assert verdict.outcome is FreshnessOutcome.NEVER_HARVESTED
    assert verdict.should_harvest is True
    assert fake.windows == []


async def test_an_empty_probe_window_skips_the_harvest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WB answering "no rows" past our history is the one proof there is nothing new."""
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY
    )

    assert verdict.outcome is FreshnessOutcome.WB_EMPTY
    assert verdict.should_harvest is False
    assert fake.windows == [(date(2026, 7, 27), date(2026, 8, 2))]


async def test_a_row_past_our_history_triggers_the_harvest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single settled row past everything held means WB published a report."""
    fake = _FakeFinanceClient(
        row=WBReportDetailRow(rrd_id=1, realizationreport_id=977216383, create_dt=date(2026, 8, 3))
    )
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY
    )

    assert verdict.outcome is FreshnessOutcome.WB_HAS_NEW
    assert verdict.should_harvest is True


async def test_a_failed_probe_harvests_anyway(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unanswered probe is not a "no" — the gate fails open.

    Failing closed would let one rate-limit or 5xx from WB postpone a settlement
    week out of the P&L, and the log line for it would be indistinguishable from
    a quiet week.
    """
    fake = _FakeFinanceClient(error=IntegrationError("429 from WB"))
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY
    )

    assert verdict.outcome is FreshnessOutcome.PROBE_FAILED
    assert verdict.should_harvest is True


async def test_a_history_reaching_yesterday_records_that_nothing_was_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict has to say WHY it skipped, not just that it did.

    "Nothing was asked because there was nothing to ask about" and "WB was asked
    and answered empty" are both correct reasons to skip, and the page words
    them differently — the first is not a statement about what WB published.
    """
    fake = _FakeFinanceClient()
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=date(2026, 8, 2), held_ends=[date(2026, 8, 2)], today=TODAY
    )

    assert verdict.outcome is FreshnessOutcome.UP_TO_DATE
    assert verdict.should_harvest is False
    assert fake.windows == []


async def test_a_verdict_from_a_real_request_carries_the_window_it_asked_about(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window is what makes «спросили» checkable rather than a claim."""
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=date(2026, 7, 26), held_ends=[], today=TODAY
    )

    assert verdict is not None
    assert (verdict.probe_from, verdict.probe_to) == (date(2026, 7, 27), date(2026, 8, 2))


async def test_a_verdict_reached_without_a_request_names_no_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No request was made, so there is no window — and none may be implied."""
    fake = _FakeFinanceClient()
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    verdict = await check_freshness(
        tokens=_tokens(), latest_settled=None, held_ends=[], today=TODAY
    )

    assert verdict.probe_from is None
    assert verdict.probe_to is None


# --- WBFinanceClient.fetch_first_row -------------------------------------


async def test_an_empty_window_answers_204_and_reads_as_no_rows() -> None:
    """WB's empty-window answer is 204 No Content, not a 200 with ``[]``.

    Verified live on 2026-08-04. A probe that only recognised an empty list would
    treat every quiet day as an unexpected shape and raise.
    """
    client = _client(lambda _request: httpx.Response(204))

    async with client:
        row = await client.fetch_first_row(date_from=date(2026, 8, 3), date_to=date(2026, 8, 3))

    assert row is None


async def test_the_probe_names_the_report_it_found() -> None:
    """The row carries the report id and create date the gate logs."""
    payload = [
        {
            "rrd_id": 3131730634937,
            "realizationreport_id": 977216383,
            "create_dt": "2026-08-03",
            "date_from": "2026-08-01",
            "date_to": "2026-08-02",
            "rr_dt": "2026-08-01",
        }
    ]
    client = _client(lambda _request: httpx.Response(200, json=payload))

    async with client:
        row = await client.fetch_first_row(date_from=date(2026, 8, 1), date_to=date(2026, 8, 2))

    assert row is not None
    assert row.realizationreport_id == 977216383
    assert row.create_dt == date(2026, 8, 3)


async def test_the_probe_costs_one_request_and_does_not_walk_the_report() -> None:
    """The gate must stay cheap — pagination here would defeat its whole purpose.

    The harvest follows the ``rrdid`` cursor over the whole window, a request
    at a time; if the probe ever did the same, the "is there anything new?"
    question would cost as much as the harvest it is meant to avoid.
    """
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"rrd_id": 1, "realizationreport_id": 42}])

    client = _client(handler)

    async with client:
        await client.fetch_first_row(date_from=date(2026, 8, 1), date_to=date(2026, 8, 2))

    assert len(calls) == 1
    assert calls[0].url.params["limit"] == "1"
