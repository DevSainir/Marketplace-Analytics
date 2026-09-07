"""One workspace's harvest still commits whole, now that it streams.

The finance report is no longer fetched and then written — it is written page by
page as it arrives, because holding a settlement window is what OOM-killed the
2026-08-11 harvest. That trades a memory bound for a correctness hazard: a walk
that dies half-way now dies with rows already in the transaction, and a
half-ingested settlement window does not look like an error. It looks like a
quiet week (`docs/finreports/PNL.md` §1).

`harvest_workspace` answers that with a SAVEPOINT around the walk, and these
tests exercise the real function against real PostgreSQL — fake WB, real
transaction semantics. Testing `begin_nested` on its own would prove that
PostgreSQL has savepoints, not that the harvest uses one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import date
from types import TracebackType
from typing import Any, Self

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.exceptions import IntegrationError
from src.modules.finreports.tasks import harvest as harvest_module
from src.modules.finreports.tasks import settlement as settlement_module
from src.modules.finreports.tasks.harvest import harvest_workspace
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916616")
_REPORT = 969371539
_RRD_BASE = 920_000_000_000

#: never waits out `_STORAGE_PACE_SECONDS`.
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

    #: Set by the test: True makes the second page raise, as a WB timeout does.
    fail_mid_walk = False

    async def iter_report_pages(
        self, *, date_from: date, date_to: date
    ) -> AsyncGenerator[list[WBReportDetailRow], None]:
        """Yield one page, then either a second page or WB giving up."""
        yield [_settlement(1), _settlement(2)]
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

    ``AsyncSessionLocal`` is swapped for the fixture's factory so the harvest's
    commit lands in the test's connection (and is rolled back with it) instead
    of the developer's database. Summary warming is stubbed out: it opens its
    own session, and it is explicitly best-effort, so it is not part of the
    property under test.
    """
    monkeypatch.setattr(harvest_module, "AsyncSessionLocal", session_factory)
    # The settlement walk keeps its own session and its own client: it commits
    # a week at a time, outside the transaction the rest of the harvest shares.
    monkeypatch.setattr(settlement_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(settlement_module, "WBFinanceClient", _FakeFinanceClient)
    monkeypatch.setattr(
        settlement_module, "settlement_walk_rate_gate", lambda *_a, **_kw: _OpenGate()
    )
    monkeypatch.setattr(harvest_module, "WBContentClient", _EmptyContentClient)

    async def no_warming(*, workspace_id: uuid.UUID, name: str) -> None:
        return None

    _FakeFinanceClient.fail_mid_walk = False
    yield _FakeFinanceClient
    _FakeFinanceClient.fail_mid_walk = False


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
    assert await _settled_rows(db_session) == 3
    assert await _storage_rows(db_session) == 1


async def test_a_walk_that_dies_mid_page_leaves_no_settlement_rows(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """The page written before the failure is rolled back; the harvest is not.

    Without the savepoint this commits two of the week's three rows and
    reports success — a settlement week that is 33 % short and reads as real.
    The savepoint is per WEEK now rather than per harvest, which narrows what
    a failure discards but not what it must never leave behind.
    """
    wb.fail_mid_walk = True

    counts = await harvest_workspace(tokens=_tokens(), date_from=_FROM, date_to=_TO, on_date=_TO)

    assert counts["finance"] == 0
    assert await _settled_rows(db_session) == 0
    # The rest of the harvest still committed — a failed WB source has never
    # been a reason to throw away the sources that worked.
    assert await _storage_rows(db_session) == 1


async def test_the_walk_inside_the_transaction_retries_less_than_the_default(
    wb: type[_FakeFinanceClient], db_session: AsyncSession
) -> None:
    """The client is built with a bounded ladder, because the transaction is open.

    PostgreSQL kills a session left idle in a transaction for 5 minutes. The
    default ladder sleeps longer than that between attempts on one page, so the
    server would terminate the harvest's connection mid-window rather than the
    harvest recording a failed source.
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

    assert [client.max_retries for client in built] == [settlement_module.MAX_RETRIES]
    assert settlement_module.MAX_RETRIES < 4
