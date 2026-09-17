"""The orders lane — what makes «Заказы» older than the funnel possible.

The analytics funnel answers for a rolling window, so a кабинет has funnel days
from the moment this service started harvesting it and settlements from long
before. The statistics ORDERS feed has no such horizon, which is the whole
reason this lane exists; what has to be right is the walking of it.

Unit tier: the WB client and the ingestion are faked, because what is under test
is the cursor — when the walk asks again, from where, and when it decides it is
done. A cursor that does not advance is an infinite walk against an endpoint
metered at three requests a minute.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

import pytest

from src.integrations.wildberries.clients.statistics import WBOrderPage
from src.integrations.wildberries.schemas import WBOrderRecord
from src.modules.monitoring.services import orders_walk
from src.modules.monitoring.services.orders_walk import ORDERS_EPOCH, advance_orders
from src.modules.workspaces.contract import WorkspaceTokenBundle

pytestmark = pytest.mark.unit

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000beef")


def _bundle(statistics: str = "token") -> WorkspaceTokenBundle:
    """A workspace carrying just the token this lane needs."""
    return WorkspaceTokenBundle(
        workspace_id=WORKSPACE,
        name="Демо",
        statistics=statistics,
    )


def _record(srid: str, *, changed: str, ordered: str = "2024-07-11T10:00:00") -> WBOrderRecord:
    """One order line, only the fields the walk reads."""
    return WBOrderRecord.model_validate(
        {
            "srid": srid,
            "nmId": 1,
            "date": ordered,
            "lastChangeDate": changed,
            "priceWithDisc": 1000,
            "finishedPrice": 900,
        }
    )


@pytest.fixture
def walked(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record what the walk asked WB for, and what it stored."""
    seen: dict[str, Any] = {"ingested": []}

    class _FakeClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def fetch_orders_page(self, *, changed_since: object) -> WBOrderPage:
            seen["asked_from"] = changed_since
            return seen["page"]

    class _FakeIngestion:
        async def ingest_orders(self, records: list[WBOrderRecord]) -> int:
            seen["ingested"].extend(records)
            return len(records)

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def commit(self) -> None:
            return None

    class _FakeOrders:
        def __init__(self, _session: object) -> None:
            pass

        async def covered_span(self, *, workspace_id: uuid.UUID) -> tuple[date | None, date | None]:
            return seen.get("span", (None, None))

    monkeypatch.setattr(orders_walk, "build_statistics_client", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(orders_walk, "build_ingestion_service", lambda _s: _FakeIngestion())
    monkeypatch.setattr(orders_walk, "AsyncSessionLocal", _FakeSession)
    monkeypatch.setattr(orders_walk, "OrderRepository", _FakeOrders)
    return seen


async def test_a_walk_with_no_cursor_asks_for_everything(walked: dict[str, Any]) -> None:
    """The first tick starts before WB existed, so WB answers with the first order.

    Any later start would silently define the кабинет's history as beginning
    when we happened to ask.
    """
    walked["page"] = WBOrderPage(records=[], next_cursor=None)

    await advance_orders(_bundle(), cursor=None)

    assert walked["asked_from"].date() == ORDERS_EPOCH


async def test_a_full_page_resumes_from_its_newest_change(walked: dict[str, Any]) -> None:
    """The cursor is WB's own stamp, so the next page continues where this ended."""
    walked["page"] = WBOrderPage(
        records=[_record("a", changed="2024-08-01T00:00:00")],
        next_cursor=datetime(2024, 8, 1, 0, 0),
    )

    step = await advance_orders(_bundle(), cursor=None)

    assert step.cursor == "2024-08-01T00:00:00"
    assert step.finished is False


async def test_a_short_page_ends_the_walk(walked: dict[str, Any]) -> None:
    """Less than a full page means there is nothing after it.

    The lane then stops re-enqueueing, which matters more than it looks: this
    endpoint is metered at three requests a minute and shared with the nightly
    increment.
    """
    walked["page"] = WBOrderPage(
        records=[_record("a", changed="2026-09-01T00:00:00")], next_cursor=None
    )
    walked["span"] = (date(2024, 7, 11), date(2026, 9, 1))

    step = await advance_orders(_bundle(), cursor=None)

    assert step.finished is True
    assert step.cursor is None
    assert "11.07.2024" in step.message


async def test_a_кабинет_without_the_statistics_token_is_finished_not_failed(
    walked: dict[str, Any],
) -> None:
    """No token is a lane that has nothing to do, not a lane that broke.

    A failed lane is retried and reported red on the seller's profile; this one
    is simply a кабинет whose «Статистика» scope we were never given.
    """
    step = await advance_orders(_bundle(statistics=""), cursor=None)

    assert step.finished is True
    assert "Статистика" in step.message
    assert walked["ingested"] == []
