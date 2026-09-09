"""Component tests for the stock-balance surface (``/v1/finreports/balance``).

The grid arithmetic lives in ``tests/unit/finreports/test_stock_balance.py``;
what is proved here is the transport: the active workspace scopes both the read
and the pin, the snapshot day defaults to the newest one on record rather than
to «today», and the stock itself is resolved through the monitoring contract in
the ROUTER — the balance service never reaches into another module.

The monitoring loaders are monkeypatched at the router module, exactly like the
per-SKU report's: they take the raw session, and the component tier's session is
a tripwire that fails on any real database use.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_balance_service
from src.modules.finreports.schemas import BalanceCell, BalanceResponse, BalanceSkuRow
from src.modules.monitoring.contract import WarehouseStock
from src.modules.organizations.contract import SubscriptionState
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 953770957
LATEST_DAY = date(2026, 8, 3)
FIRST_DAY = date(2026, 1, 1)


class _StubBalanceService:
    """Records what the route resolves and hands in."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def get_balance(self, **kwargs: Any) -> BalanceResponse:
        """Echo the resolved inputs back through a canned grid."""
        self.calls.append(kwargs)
        return BalanceResponse(
            stat_date=kwargs["stat_date"],
            available_from=kwargs["span"][0],
            available_to=kwargs["span"][1],
            currency="KGS",
            rows=[
                BalanceSkuRow(
                    nm_id=NM_ID,
                    sa_name="m-trx01-blk",
                    subject_name="Брюки",
                    brand_name="NORTH LINE",
                    cost_price=Decimal("800"),
                    cells=[
                        BalanceCell(
                            warehouse_name="Тула",
                            quantity=72,
                            in_way=5,
                            balance=Decimal("57600"),
                            in_way_balance=Decimal("4000"),
                        )
                    ],
                )
            ],
            pinned_skus=[],
            pinned_warehouses=["Коледино"],
            uncounted_warehouses=["СЦ Брак"],
            uncounted_skus=[],
            uncosted_count=0,
            notes=[],
        )

    async def set_pin(self, **kwargs: Any) -> None:
        """Record a pin toggle without touching a database."""
        self.calls.append({"set_pin": kwargs})


@pytest.fixture
def balance() -> _StubBalanceService:
    """The stub balance service the route is wired to."""
    return _StubBalanceService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    balance: _StubBalanceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire identity, tenancy, the stub service and the contract loaders."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_balance_service, balance)

    async def _span(session: Any, **_kw: Any) -> tuple[date, date]:
        return (FIRST_DAY, LATEST_DAY)

    async def _stock(session: Any, **kwargs: Any) -> dict[tuple[int, str], WarehouseStock]:
        cells = {(NM_ID, "Тула"): WarehouseStock(72, 5)}
        return cells if kwargs["stat_date"] == LATEST_DAY else {}

    async def _vendor_codes(session: Any, **_kw: Any) -> dict[int, str]:
        return {NM_ID: "m-trx01-blk"}

    monkeypatch.setattr("src.modules.finreports.routers.balance.stock_day_span", _span)
    monkeypatch.setattr("src.modules.finreports.routers.balance.load_stock_by_warehouse", _stock)
    monkeypatch.setattr("src.modules.finreports.routers.balance.load_vendor_codes", _vendor_codes)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_grid_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    balance: _StubBalanceService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the grid.

    The balance is built from the seller's stock and their own cost prices;
    resolving either without tenancy would price one tenant's warehouse with
    another's figures.
    """
    response = await client.get("/api/v1/finreports/balance", headers=headers)

    assert response.status_code == 200
    assert balance.calls[0]["workspace_id"] == workspace.id


async def test_an_omitted_day_falls_back_to_the_newest_snapshot(
    client: httpx.AsyncClient, headers: dict[str, str], balance: _StubBalanceService
) -> None:
    """No day means the last day WB actually captured — never «today».

    Today's snapshot usually does not exist yet, and defaulting to it would open
    the page on an empty balance every morning.
    """
    response = await client.get("/api/v1/finreports/balance", headers=headers)

    assert balance.calls[0]["stat_date"] == LATEST_DAY
    assert response.json()["stat_date"] == LATEST_DAY.isoformat()


async def test_a_picked_day_is_passed_through_with_that_day_s_stock(
    client: httpx.AsyncClient, headers: dict[str, str], balance: _StubBalanceService
) -> None:
    """The picked day selects the snapshot; a day without one yields no stock."""
    await client.get(
        "/api/v1/finreports/balance", params={"stat_date": "2026-07-04"}, headers=headers
    )

    call = balance.calls[0]
    assert call["stat_date"] == date(2026, 7, 4)
    assert call["stock"] == {}


async def test_the_stock_reaches_the_service_through_the_route(
    client: httpx.AsyncClient, headers: dict[str, str], balance: _StubBalanceService
) -> None:
    """Stock and catalogue names come from the monitoring contract, not the
    service — which keeps the service module-pure and unit-testable."""
    await client.get("/api/v1/finreports/balance", headers=headers)

    call = balance.calls[0]
    assert call["stock"] == {(NM_ID, "Тула"): WarehouseStock(72, 5)}
    assert call["vendor_codes"] == {NM_ID: "m-trx01-blk"}
    assert call["span"] == (FIRST_DAY, LATEST_DAY)


async def test_the_response_serialises_the_grid_shape_the_table_reads(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The wire shape is the frontend contract — pin the field names."""
    response = await client.get("/api/v1/finreports/balance", headers=headers)

    body = response.json()
    row = body["rows"][0]
    assert row["cells"][0] == {
        "warehouse_name": "Тула",
        "quantity": 72,
        "in_way": 5,
        "balance": "57600",
        "in_way_balance": "4000",
    }
    for field in ("sa_name", "subject_name", "brand_name", "cost_price"):
        assert field in row
    # The marks travel with the grid: the client draws the panels, so it needs
    # to know which columns are pinned and which are out of the count.
    assert body["pinned_warehouses"] == ["Коледино"]
    assert body["uncounted_warehouses"] == ["СЦ Брак"]
    assert body["available_from"] == FIRST_DAY.isoformat()
    assert body["uncosted_count"] == 0


async def test_a_pin_is_persisted_for_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    balance: _StubBalanceService,
    workspace: Workspace,
) -> None:
    """Pinning a warehouse column reaches the service with the workspace."""
    response = await client.put(
        "/api/v1/finreports/balance/pins",
        json={"kind": "warehouse", "value": "Тула", "pinned": True},
        headers=headers,
    )

    assert response.status_code == 204
    assert balance.calls[0]["set_pin"] == {
        "workspace_id": workspace.id,
        "kind": "warehouse",
        "value": "Тула",
        "pinned": True,
    }


async def test_marking_a_warehouse_uncounted_reaches_the_service(
    client: httpx.AsyncClient, headers: dict[str, str], balance: _StubBalanceService
) -> None:
    """«Не считать» is a mark of its own, not a pin with a flag.

    It does the opposite of a pin — the column sorts last and leaves every
    total — so it needs its own kind rather than overloading the pin's value.
    """
    response = await client.put(
        "/api/v1/finreports/balance/pins",
        json={"kind": "warehouse_uncounted", "value": "СЦ Брак", "pinned": True},
        headers=headers,
    )

    assert response.status_code == 204
    assert balance.calls[0]["set_pin"]["kind"] == "warehouse_uncounted"
    assert balance.calls[0]["set_pin"]["value"] == "СЦ Брак"


async def test_a_mark_of_an_unknown_kind_is_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], balance: _StubBalanceService
) -> None:
    """Only the three known kinds are accepted — anything else is a 422.

    The kind decides how the stored value is read back; accepting a free-text
    one would write a mark nothing can ever match or clear.
    """
    response = await client.put(
        "/api/v1/finreports/balance/pins",
        json={"kind": "region", "value": "Центр", "pinned": True},
        headers=headers,
    )

    assert response.status_code == 422
    assert balance.calls == []


async def test_a_pin_stops_saving_once_the_term_is_past_grace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    balance: _StubBalanceService,
    login_as: Callable[..., None],
) -> None:
    """The balance grid's pins are a write like any other.

    They were the last unguarded one in this module — everything here that
    touches a settlement figure already refused a lapsed term, and a pin
    slipping through made the rule look arbitrary rather than deliberate.
    """
    login_as(subscription=SubscriptionState.EXPIRED)

    response = await client.put(
        "/api/v1/finreports/balance/pins",
        json={"kind": "warehouse", "value": "Тула", "pinned": True},
        headers=headers,
    )

    assert response.status_code == 403
    assert balance.calls == []
