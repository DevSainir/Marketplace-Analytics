"""What a harvest keeps when the settlement walk dies part-way.

The finance report is not fetched and then written — it is written as it
arrives, because holding a settlement window is what OOM-killed the 2026-08-11
harvest. That trades a memory bound for a correctness hazard: a walk that dies
half-way dies with rows already committed, and a half-ingested settlement window
does not look like an error. It looks like a quiet week
(`docs/finreports/PNL.md` §1).

**The unit that is all-or-nothing is the batch**, and has been since the walk
started streaming its pages (2026-09-17). Not the week — WB serves this endpoint
four times an hour and no transaction may be held across that wait — and no
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
from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks import storage as storage_module
from src.modules.finreports.tasks.harvest import (
    harvest_workspace,
    persistence,
    sources,
    workspace,
)
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916616")
_REPORT = 969371539
_RRD_BASE = 920_000_000_000

#: never waits out `storage._STORAGE_PACE_SECONDS`.
_FROM, _TO = date(2026, 7, 13), date(2026, 7, 15)


def _tokens() -> WorkspaceTokenBundle:
    """A workspace with both scopes, so every source in the harvest runs.

    organisation alone, and this test needs a source other than finance in the
    same transaction to have anything to say about atomicity.
    """
    return WorkspaceTokenBundle(
        workspace_id=_WORKSPACE,
        name="Демо",
        statistics="stat-token",
        analytics="analytics-token",
        content="content-token",
        internal_features=True,
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

    async def acquire(self, endpoint: str) -> None:
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
        self, *, date_from: date, date_to: date, cursor: int = 0
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


class _FakeStorageClient:

    def __init__(self, _settings: Any, *, token: str) -> None:
        self.token = token

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

        return [
                {
                    "date": date_from.isoformat(),
                    "warehouse": "Бишкек",
                    "giId": 5001,
                    "chrtId": 6001,
                    "nmId": 902754830,
                    "volume": "1.4",
                    "warehousePrice": "0.31",
                }
            )
        ]


class _EmptyMeasurementClient:

    def __init__(self, _settings: Any, *, token: str) -> None:
        self.token = token

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def fetch_penalties(self, *, date_from: date, date_to: date) -> list[Any]:
        return []

        return []


class _EmptyContentClient:
    """A catalogue with no dimensioned cards."""

    def __init__(self, _settings: Any, *, token: str) -> None:
        self.token = token

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def fetch_all_cards(self) -> list[Any]:
        """No cards."""
        return []


@pytest.fixture
def wb(
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker[AsyncSession]
) -> Iterator[type[_FakeFinanceClient]]:
    """Point the harvest at fake WB clients and the test transaction.

    ``AsyncSessionLocal`` is swapped on `harvest.persistence`, which owns every
    write outside the settlement walk, for the fixture's factory so the harvest's
    commit lands in the test's connection (and is rolled back with it) instead
    of the developer's database. Summary warming is stubbed out: it opens its
    own session, and it is explicitly best-effort, so it is not part of the
    property under test.
    """
    monkeypatch.setattr(persistence, "AsyncSessionLocal", session_factory)
    # The settlement walk keeps its own session and its own client: it commits
    # a week at a time, outside the transaction the rest of the harvest shares.
    monkeypatch.setattr(settlement_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(settlement_module, "WBFinanceClient", _FakeFinanceClient)
    monkeypatch.setattr(
        settlement_module, "settlement_walk_rate_gate", lambda *_a, **_kw: _OpenGate()
    )
    monkeypatch.setattr(sources, "WBContentClient", _EmptyContentClient)

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


async def _storage_rows(session: AsyncSession) -> int:
    """Billed-volume observations, the harvest's other write."""
    return int(
        (
            await session.execute(
            )
        ).scalar_one()
    )


async def test_a_completed_harvest_commits_every_page(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """All three settlement rows land, across the two pages they arrived in."""
    counts = await harvest_workspace(tokens=_tokens(), date_from=_FROM, date_to=_TO, on_date=_TO)

    assert counts["finance"] == 3
    assert counts["finance_windows_failed"] == 0
    assert await _settled_rows(db_session) == 3
    assert await _storage_rows(db_session) == 1


async def test_a_walk_that_dies_mid_page_leaves_no_settlement_rows(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """The request that failed leaves nothing behind; the ones before it stand.

    WB serves this endpoint once per quarter of an hour, and no transaction may
    be held open across that wait — so the first request's two rows are
    committed and kept, the failed request contributes nothing, and the week is
    reported incomplete, which is what `finance_windows_failed` is for.
    """
    wb.fail_mid_walk = True

    counts = await harvest_workspace(tokens=_tokens(), date_from=_FROM, date_to=_TO, on_date=_TO)

    assert counts["finance"] == 2
    assert counts["finance_windows_failed"] == 1
    assert await _settled_rows(db_session) == 2
    # The rest of the harvest still committed — a failed WB source has never
    # been a reason to throw away the sources that worked.
    assert await _storage_rows(db_session) == 1


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

    counts = await harvest_workspace(tokens=_tokens(), date_from=_FROM, date_to=_TO, on_date=_TO)

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
        await harvest_workspace(tokens=_tokens(), date_from=_FROM, date_to=_TO, on_date=_TO)
    finally:
        _FakeFinanceClient.__init__ = original  # type: ignore[method-assign]

    # One client per page, and every one of them bounded — the walk builds a
    # fresh client for each request now that each request has its own
    # transaction, so a ladder set on only the first would still park the rest.
    assert built
    assert {client.max_retries for client in built} == {settlement_module.MAX_RETRIES}
    assert settlement_module.MAX_RETRIES < 4
