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
from datetime import date
from typing import Any

import httpx
import pytest

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.finance import WBFinanceClient
from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.freshness import has_unharvested_report, probe_window
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

    client = WBFinanceClient(settings, token="stat-token")
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


def test_the_probe_window_starts_the_day_after_the_last_settled_day() -> None:
    """Days already covered are excluded, so any row found belongs to a new report."""
    window = probe_window(latest_settled=date(2026, 8, 2), today=TODAY)

    assert window == (date(2026, 8, 3), date(2026, 8, 3))


def test_the_probe_window_never_includes_today() -> None:
    """WB serves no data for the current day, so asking about it proves nothing."""
    window = probe_window(latest_settled=date(2026, 7, 20), today=TODAY)

    assert window == (date(2026, 7, 21), date(2026, 8, 3))


def test_there_is_no_probe_window_once_settled_through_yesterday() -> None:
    """No unseen day exists, so the gate can answer without spending a request."""
    window = probe_window(latest_settled=date(2026, 8, 3), today=TODAY)

    assert window is None


def test_a_report_settling_past_yesterday_still_yields_no_window() -> None:
    """A period ending in the future must not invert the window into a valid range.

    WB states a report's period itself, and it has served ``date_to`` a day past
    the last settled row; an inverted range would be sent to WB as dateFrom >
    dateTo and answered unpredictably.
    """
    window = probe_window(latest_settled=date(2026, 8, 10), today=TODAY)

    assert window is None


# --- has_unharvested_report ----------------------------------------------


async def test_a_never_harvested_workspace_is_harvested_without_asking_wb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Everything WB holds is new, so the probe would only cost a request."""
    fake = _FakeFinanceClient()
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    decision = await has_unharvested_report(tokens=_tokens(), latest_settled=None, today=TODAY)

    assert decision is True
    assert fake.windows == []


async def test_an_empty_probe_window_skips_the_harvest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WB answering "no rows" past our history is the one proof there is nothing new."""
    fake = _FakeFinanceClient(row=None)
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    decision = await has_unharvested_report(
        tokens=_tokens(), latest_settled=date(2026, 8, 2), today=TODAY
    )

    assert decision is False
    assert fake.windows == [(date(2026, 8, 3), date(2026, 8, 3))]


async def test_a_row_past_our_history_triggers_the_harvest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single settled row past everything held means WB published a report."""
    fake = _FakeFinanceClient(
        row=WBReportDetailRow(rrd_id=1, realizationreport_id=977216383, create_dt=date(2026, 8, 3))
    )
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    decision = await has_unharvested_report(
        tokens=_tokens(), latest_settled=date(2026, 7, 26), today=TODAY
    )

    assert decision is True


async def test_a_failed_probe_harvests_anyway(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unanswered probe is not a "no" — the gate fails open.

    Failing closed would let one rate-limit or 5xx from WB postpone a settlement
    week out of the P&L, and the log line for it would be indistinguishable from
    a quiet week.
    """
    fake = _FakeFinanceClient(error=IntegrationError("429 from WB"))
    monkeypatch.setattr(freshness, "WBFinanceClient", fake)

    decision = await has_unharvested_report(
        tokens=_tokens(), latest_settled=date(2026, 8, 2), today=TODAY
    )

    assert decision is True


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

    ``iter_report_pages`` follows the ``rrdid`` cursor over the whole window; if
    the probe ever did the same, the "is there anything new?" question would
    cost as much as the harvest it is meant to avoid.
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
