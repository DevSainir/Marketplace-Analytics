"""The freshness gate, now that WB will simply list its own reports.

The gate decides whether a tick walks WB at all, so its two ways of being
wrong are not symmetric. Skipping a harvest that should have run leaves a
settlement week out of the P&L silently — which is what happened for three
days in August 2026 when the harvest task was crashing, and nothing in the
product could tell that apart from «WB published nothing». Running one that
was not needed costs a paced request and nothing else.

Since 2026-09-22 the question is asked outright rather than inferred. The old
endpoint had no list method, so the gate spent a settlement request probing
for a row and `services/publication.py` derived a calendar to avoid spending
it; `POST /api/finance/v1/sales-reports/list` answers directly, on a bucket of
its own.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.modules.finreports.services.freshness_record import FreshnessOutcome
from src.modules.finreports.tasks import freshness
from src.modules.finreports.tasks.freshness import check_freshness, outstanding_reports
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 22)
SETTLED = date(2026, 9, 6)


def _tokens(*, finance: str = "a-finance-token") -> WorkspaceTokenBundle:
    """A workspace bundle with the "Finance" token the report needs."""
    return WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="Demo", finance=finance)


def _header(report_id: int, date_to: date, *, created: date | None = None) -> dict[str, Any]:
    """One report as `sales-reports/list` serves it."""
    return {
        "reportId": report_id,
        "dateFrom": (date_to - __import__("datetime").timedelta(days=6)).isoformat(),
        "dateTo": date_to.isoformat(),
        "createDate": (created or date_to + __import__("datetime").timedelta(days=1)).isoformat(),
        "currency": "KGS",
        "reportType": 1,
    }


class _FakeClient:
    """Records the windows it was asked to list, so «asked nothing» is checkable."""

    def __init__(self, headers: list[dict[str, Any]] | None = None, error: Exception | None = None):
        self.headers = headers or []
        self.error = error
        self.calls: list[tuple[date, date]] = []

    def __call__(self, *_args: object, **_kwargs: object) -> _FakeClient:
        return self

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def list_reports(self, *, date_from: date, date_to: date) -> list[Any]:
        self.calls.append((date_from, date_to))
        if self.error is not None:
            raise self.error
        from src.integrations.wildberries.schemas import WBFinanceReportHeader

        return [WBFinanceReportHeader.model_validate(h) for h in self.headers]


def _install(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> _FakeClient:
    """Point the gate at a fake WB."""
    monkeypatch.setattr(freshness, "WBFinanceReportsClient", client)
    return client


# --- outstanding_reports --------------------------------------------------


async def test_a_report_we_do_not_hold_is_the_work(monkeypatch: pytest.MonkeyPatch) -> None:
    """WB names its reports; we subtract the ones on file. No arithmetic."""
    client = _install(
        monkeypatch,
        _FakeClient([_header(901, date(2026, 9, 13)), _header(902, date(2026, 9, 20))]),
    )

    outstanding, _listed = await outstanding_reports(tokens=_tokens(), held={901}, today=TODAY)

    assert outstanding is not None
    assert [report.report_id for report in outstanding.reports] == [902]
    assert client.calls, "the list must actually be asked for"


async def test_reports_come_back_oldest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """The walk certifies an unbroken PREFIX, so the order is load-bearing.

    A caller handed these newest-first would move the watermark over a report
    it had not fetched — the 31.08.2026 failure, one layer down.
    """
    _install(
        monkeypatch,
        _FakeClient([_header(902, date(2026, 9, 20)), _header(901, date(2026, 9, 13))]),
    )

    outstanding, _listed = await outstanding_reports(tokens=_tokens(), held=set(), today=TODAY)

    assert outstanding is not None
    assert [report.date_to for report in outstanding.reports] == [
        date(2026, 9, 13),
        date(2026, 9, 20),
    ]


async def test_a_report_served_out_of_order_is_still_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Holding the newer report is not holding the older one.

    This is the failure that cost every workspace 31.08.2026: the later report
    landed first, every forward-looking cursor jumped past the earlier one, and
    the day became unreachable. Ids cannot express that mistake — the older id
    is either held or it is not.
    """
    _install(
        monkeypatch,
        _FakeClient([_header(901, date(2026, 9, 13)), _header(902, date(2026, 9, 20))]),
    )

    outstanding, _listed = await outstanding_reports(tokens=_tokens(), held={902}, today=TODAY)

    assert outstanding is not None
    assert [report.report_id for report in outstanding.reports] == [901]


async def test_holding_everything_wb_lists_is_nothing_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case, and it costs one cheap request rather than a walk."""
    _install(monkeypatch, _FakeClient([_header(901, date(2026, 9, 13))]))

    outstanding, _listed = await outstanding_reports(tokens=_tokens(), held={901}, today=TODAY)

    assert outstanding is None


# --- check_freshness ------------------------------------------------------


async def test_a_new_report_is_recorded_and_handed_to_the_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict says what was found; the second half says what to fetch."""
    _install(monkeypatch, _FakeClient([_header(902, date(2026, 9, 20))]))

    verdict, missing, _listed = await check_freshness(
        tokens=_tokens(), latest_settled=SETTLED, held=set(), today=TODAY
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.WB_HAS_NEW
    assert verdict.should_harvest is True
    assert [report.report_id for report in missing] == [902]


async def test_nothing_missing_skips_without_a_walk(monkeypatch: pytest.MonkeyPatch) -> None:
    """`UP_TO_DATE` now means «we hold every report WB has formed», which is
    WB's own answer rather than a silence we chose to read as a no."""
    _install(monkeypatch, _FakeClient([_header(901, date(2026, 9, 13))]))

    verdict, missing, _listed = await check_freshness(
        tokens=_tokens(), latest_settled=SETTLED, held={901}, today=TODAY
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.UP_TO_DATE
    assert verdict.should_harvest is False
    assert missing == ()


async def test_an_unanswered_list_harvests_anyway(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate fails open. An unanswered question is not a "no".

    Failing closed would let one 5xx postpone a settlement week out of the
    P&L, and the log line for it would be indistinguishable from a quiet week.
    """
    _install(monkeypatch, _FakeClient(error=IntegrationError("WB did not answer.")))

    verdict, missing, _listed = await check_freshness(
        tokens=_tokens(), latest_settled=SETTLED, held=set(), today=TODAY
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.PROBE_FAILED
    assert verdict.should_harvest is True
    assert missing == ()


async def test_a_workspace_without_a_finance_token_is_not_silently_up_to_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A seller we cannot ask for is short a P&L, not finished.

    Reporting `UP_TO_DATE` here would put "loaded through yesterday" over a
    statement nobody is fetching. `None` leaves the standing verdict alone and
    the log says why.
    """
    client = _install(monkeypatch, _FakeClient([_header(902, date(2026, 9, 20))]))

    verdict, missing, _listed = await check_freshness(
        tokens=_tokens(finance=""), latest_settled=SETTLED, held=set(), today=TODAY
    )

    assert verdict is None
    assert missing == ()
    assert client.calls == [], "no token means no request"


async def test_the_verdict_names_the_span_it_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorded window is what makes "asked" checkable rather than a claim."""
    _install(
        monkeypatch,
        _FakeClient([_header(901, date(2026, 9, 13)), _header(902, date(2026, 9, 20))]),
    )

    verdict, _missing, _listed = await check_freshness(
        tokens=_tokens(), latest_settled=SETTLED, held=set(), today=TODAY
    )

    assert verdict is not None
    assert (verdict.probe_from, verdict.probe_to) == (date(2026, 9, 13), date(2026, 9, 20))


async def test_the_list_window_reaches_past_the_latest_lateness_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A report WB serves late must still be inside the window we ask about.

    The record is eight days (a report stamped 01.09.2026 and first served on
    09.09). The list is one request whatever its width, so the
    window is sized for the worst case rather than for the common one.
    """
    client = _install(monkeypatch, _FakeClient([]))

    await outstanding_reports(tokens=_tokens(), held=set(), today=TODAY)

    asked_from, asked_to = client.calls[0]
    assert (TODAY - asked_from).days >= 30
    assert asked_to == TODAY


async def test_a_late_report_is_handed_over_at_whatever_hour_it_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No hour is the wrong hour to fetch a report WB has already formed.

    A decaying cadence used to hold a listed-but-unheld report back to 08:00,
    12:00, 16:00 and 20:00 MSK, and for a report three days overdue to 08:00,
    14:00 and 20:00. That existed to protect a budget of about 94 settlement
    requests a day; the Finance surface serves 1 440, and the cost of asking
    early is now one request against a report the seller can already see on WB's
    own site.

    Asserted through the gate rather than by the absence of a call, because
    «which hour is it» is no longer an input the gate has.
    """
    long_overdue = _header(902, date(2026, 9, 1), created=date(2026, 9, 2))
    _install(monkeypatch, _FakeClient([long_overdue]))

    verdict, missing, _listed = await check_freshness(
        tokens=_tokens(), latest_settled=SETTLED, held=set(), today=TODAY
    )

    assert verdict is not None
    assert verdict.outcome is FreshnessOutcome.WB_HAS_NEW
    assert [report.report_id for report in missing] == [902]


class _BucketGate:
    """A gate whose detail bucket reports a fixed wait."""

    def __init__(self, wait: float) -> None:
        self._wait = wait

    async def retry_after(self, _endpoint: str, *, reserve_seconds: float = 0.0) -> float:
        return self._wait


@pytest.mark.parametrize(("wait", "blocked"), [(58.0, 0.0), (890.0, 890.0)])
async def test_a_refilling_bucket_is_not_a_block(
    monkeypatch: pytest.MonkeyPatch, wait: float, blocked: float
) -> None:
    """Up to a minute is the next token coming; hundreds of seconds is WB refusing.

    Read as a block, the minute after the backfill or the daily tail took a
    token skipped the seller with "WB closed" — and took its daily tail with it —
    over a pause the gate queues through by itself.
    """
    monkeypatch.setattr(freshness, "finance_reports_rate_gate", lambda *_a, **_k: _BucketGate(wait))
    tokens = WorkspaceTokenBundle(workspace_id=uuid.uuid4(), name="NEVA", finance="a-token")

    assert await freshness.settlement_blocked_for(tokens) == blocked
