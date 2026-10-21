"""What a harvest keeps when the settlement walk dies part-way.

The finance report is not fetched and then written — it is written as it
arrives, because holding a settlement window is what OOM-killed the 2026-08-11
harvest. That trades a memory bound for a correctness hazard: a walk that dies
half-way dies with rows already committed, and a half-ingested settlement window
does not look like an error. It looks like a quiet week
(`docs/finreports/PNL.md` §1).

**The unit that is all-or-nothing is the batch**, and has been since the walk
started streaming its pages (2026-09-17). Not the week — the walk waits for WB's
token between requests (four an hour on the old endpoint, one a minute on
finance-api) and no transaction may be held across that wait — and no
longer the page either, because one transaction over a whole page put back the
ceiling the streaming had just removed. What makes that safe is not atomicity
but idempotence: the cursor advances only on a completed request, every row is
upserted by `rrd_id`, and the week is REPORTED incomplete so the next tick asks
again.

These tests exercise the real `harvest_workspace` against real PostgreSQL — fake
WB, real transaction semantics — because what is under test is which rows
survive a commit boundary, and a fake session cannot have one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import date
from types import TracebackType
from typing import Any, Self

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.schemas import WBReportDetailRow
from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.tasks.harvest import (
    harvest_workspace,
    persistence,
    workspace,
)
from src.modules.finreports.tasks.settlement import MissingReport
from src.modules.finreports.tasks.settlement import page as settlement_page
from src.modules.finreports.tasks.settlement import reports as settlement_module
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916616")
_REPORT = 969371539
_RRD_BASE = 920_000_000_000

#: The settlement window the fake report covers.
_FROM, _TO = date(2026, 7, 13), date(2026, 7, 15)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with a «Финансы» token, so the settlement walk runs."""
    return WorkspaceTokenBundle(
        workspace_id=_WORKSPACE,
        name="Демо",
        statistics="stat-token",
        finance="a-finance-token",
    )


def _settlement(index: int) -> WBReportDetailRow:
    """One settlement row from the window under test."""
    return WBReportDetailRow.model_validate(
        {
            "rrd_id": _RRD_BASE + index,
            "realizationreport_id": _REPORT,
            "date_from": _FROM.isoformat(),
            "date_to": _TO.isoformat(),
            "rr_dt": "2026-07-14",
            "currency_name": "KGS",
            "supplier_oper_name": "Продажа",
            "ppvz_for_pay": "1854.32",
        }
    )


class _OpenGate:
    """A rate gate with a token always available.

    The real one waits for WB's next quarter-hour, which this test has no
    interest in: what is under test is the transaction boundary around a week,
    not the wait in front of it.
    """

    async def acquire(self, endpoint: str, *, reserve_seconds: float = 0.0) -> None:
        return None

    async def observe(self, endpoint: str, remaining: int | None) -> None:
        return None


class _FakeFinanceClient:
    """Serves settlement pages, optionally dying part-way through the walk.

    Hand-written rather than a mock so that a renamed or re-signatured client
    method fails this test instead of being silently accepted.
    """

    def __init__(
        self,
        _settings: Any,
        *,
        token: str,
        max_retries: int | None = None,
        rate_gate: Any = None,
    ) -> None:
        self.token = token
        self.max_retries = max_retries
        self.rate_gate = rate_gate

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    #: Set by the test: True makes the second request raise, as a WB timeout does.
    fail_mid_walk = False

    #: Set by the test: True makes the FIRST request raise after it has already
    #: handed over a batch — the case the per-batch commit exists for, and the
    #: one no other arrangement of these fakes reaches.
    fail_after_first_batch = False

    @property
    def stream_limit(self) -> int:
        """Small, so this test's three rows still make a multi-request walk."""
        return 2

    async def stream_report_rows(
        self, *, report_id: int = 0, cursor: int = 0
    ) -> AsyncIterator[list[WBReportDetailRow]]:
        """Serve a full request, then either the last one or WB giving up."""
        if cursor == 0:
            if self.fail_after_first_batch:
                yield [_settlement(1)]
                raise IntegrationError("reportDetailByPeriod died mid-body.")
            yield [_settlement(1), _settlement(2)]
            return
        if self.fail_mid_walk:
            raise IntegrationError("reportDetailByPeriod timed out on page 2.")
        yield [_settlement(3)]


@pytest.fixture
def wb(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> Iterator[type[_FakeFinanceClient]]:
    """Point the harvest at a fake WB client and the test transaction.

    ``AsyncSessionLocal`` is swapped on `harvest.persistence`, which owns the
    watermark write, for the fixture's factory so the harvest's commits land in
    the test's connection (and are rolled back with it) instead of the
    developer's database. Rollup warming is stubbed out: it opens its own
    session, and it is explicitly best-effort, so it is not part of the property
    under test.
    """
    monkeypatch.setattr(persistence, "AsyncSessionLocal", session_factory)
    # The settlement walk keeps its own sessions and its own client: it commits
    # a batch at a time. Both halves of the settlement package own a session: `page` for the rows
    # it streams, `reports` for the header it books once one is whole.
    monkeypatch.setattr(settlement_page, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(settlement_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(settlement_page, "WBFinanceReportsClient", _FakeFinanceClient)
    monkeypatch.setattr(
        settlement_module, "finance_reports_rate_gate", lambda *_a, **_kw: _OpenGate()
    )

    async def no_warming(*, workspace_id: uuid.UUID, name: str) -> None:
        return None

    monkeypatch.setattr(workspace, "warm_settlement_rollup", no_warming)
    _FakeFinanceClient.fail_mid_walk = False
    _FakeFinanceClient.fail_after_first_batch = False
    yield _FakeFinanceClient
    _FakeFinanceClient.fail_mid_walk = False
    _FakeFinanceClient.fail_after_first_batch = False


async def _settled_rows(session: AsyncSession) -> int:
    """This window's settlement rows, as the database holds them."""
    return int(
        (
            await session.execute(
                sa.select(sa.func.count()).where(LogisticsTransaction.rrd_id >= _RRD_BASE)
            )
        ).scalar_one()
    )


async def test_a_completed_harvest_commits_every_page(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """All three settlement rows land, across the two pages they arrived in."""
    counts = await harvest_workspace(
        tokens=_tokens(), reports=(MissingReport(report_id=1, date_to=_TO),)
    )

    assert counts["finance"] == 3
    assert counts["finance_windows_failed"] == 0
    assert await _settled_rows(db_session) == 3


async def test_a_walk_that_dies_mid_page_leaves_no_settlement_rows(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """The request that failed leaves nothing behind; the ones before it stand.

    The walk waits for WB's token between requests, and no transaction may be
    held open across that wait — so the first request's two rows are
    committed and kept, the failed request contributes nothing, and the week is
    reported incomplete, which is what `finance_windows_failed` is for.
    """
    wb.fail_mid_walk = True

    counts = await harvest_workspace(
        tokens=_tokens(), reports=(MissingReport(report_id=1, date_to=_TO),)
    )

    assert counts["finance"] == 2
    assert counts["finance_windows_failed"] == 1
    assert await _settled_rows(db_session) == 2


async def test_a_request_that_dies_after_a_batch_keeps_that_batch(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """A half-read page is kept, not discarded, and the week is still called short.

    This is the trade the per-batch commit makes, and it only looks wrong until
    you count what the alternative costs: one transaction over a 100 000-row
    page is the state that OOM-killed the worker on 2026-09-15. Keeping the
    batch is safe because nothing downstream trusts a row count — the cursor did
    not advance, every row upserts by `rrd_id`, and `finance_windows_failed`
    says the week is not finished.

    The failure this pins is the tempting simplification: roll the page back on
    error. The rows would be re-fetched to exactly the same place, and 217
    seconds of WB's budget would be spent doing it.
    """
    wb.fail_after_first_batch = True

    counts = await harvest_workspace(
        tokens=_tokens(), reports=(MissingReport(report_id=1, date_to=_TO),)
    )

    assert counts["finance"] == 1
    assert counts["finance_windows_failed"] == 1
    assert await _settled_rows(db_session) == 1


async def test_the_walk_inside_the_transaction_retries_less_than_the_default(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """Every client is built with a bounded ladder, because a transaction is open.

    PostgreSQL kills a session left idle in a transaction for 5 minutes. The
    default ladder sleeps longer than that between attempts on one page, so the
    server would terminate the harvest's connection mid-page rather than the
    harvest recording a failed source — which is exactly what happened on
    2026-09-07, when a 429's demanded 897 s was slept off inside one.
    """
    built: list[_FakeFinanceClient] = []
    original = _FakeFinanceClient.__init__

    def spy(self: _FakeFinanceClient, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        built.append(self)

    _FakeFinanceClient.__init__ = spy  # type: ignore[method-assign]
    try:
        await harvest_workspace(
            tokens=_tokens(), reports=(MissingReport(report_id=1, date_to=_TO),)
        )
    finally:
        _FakeFinanceClient.__init__ = original  # type: ignore[method-assign]

    # One client per page, and every one of them bounded — the walk builds a
    # fresh client for each request now that each request has its own
    # transaction, so a ladder set on only the first would still park the rest.
    assert built
    assert {client.max_retries for client in built} == {settlement_page.MAX_RETRIES}
    assert settlement_page.MAX_RETRIES < 4
