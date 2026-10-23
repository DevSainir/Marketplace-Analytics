"""Component tests for the per-SKU P&L route (``GET /v1/finreports/pnl/skus``).

The report arithmetic lives in ``tests/unit/finreports/test_sku_report.py``;
what is proved here is the transport: the window defaults and passes through,
the active workspace scopes the read, and — specific to this route — the two
cross-module figures (orders, ad spend) are resolved through the monitoring
contract and handed to the service rather than fetched inside it.

The monitoring loaders are monkeypatched at the router module: they take the raw
session, and the component tier's session is a tripwire that fails on any real
database use.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.core.timeutils import moscow_today
from src.modules.finreports.deps import get_sku_report_service
from src.modules.finreports.schemas import (
    PnlDashboard,
    PnlSizesResponse,
    PnlSkuReportResponse,
    PnlSkuRow,
)
from src.modules.finreports.services.pnl.size_report import build_size_rows
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 900000101

#: A WB CDN rendition URL — the shape the catalogue stores and the table
#: renders straight into an ``<img src>``.
PHOTO_URL = "https://basket-01.wbbasket.ru/vol9000/part900000/900000101/images/big/1.webp"

#: Matches the router's own default window.
DEFAULT_WINDOW_DAYS = 28


def _row(**overrides: Any) -> PnlSkuRow:
    """A minimal row that still exercises every response field.

    The figures are nm 900000101 of the synthetic window in
    ``tests/unit/finreports/test_sku_report.py``, with 60 000 of its ad spend
    WB-funded, so the canned row is internally consistent.
    """
    values: dict[str, Any] = {
        "nm_id": NM_ID,
        "sa_name": "m-trx01-blk",
        "subject_name": "Trousers",
        "brand_name": "NORTH LINE",
        "is_excluded": False,
        "orders_units": 2600,
        "sold_units": 800,
        "returned_units": 80,
        "return_rate_pct": Decimal("10.00"),
        "buyout_units": 600,
        "decided_units": 800,
        "buyout_pct": Decimal("75.00"),
        "sales_amount": Decimal("2000000.00"),
        "returns_amount": Decimal("200000.00"),
        "revenue_paid": Decimal("1800000.00"),
        "revenue_seller_price": Decimal("2160000.00"),
        "spp_amount": Decimal("360000.00"),
        "spp_pct": Decimal("16.67"),
        "average_cheque": Decimal("2500.00"),
        "logistics_forward": Decimal("200000.00"),
        "logistics_return": Decimal("48000.00"),
        "logistics_total": Decimal("248000.00"),
        "logistics_pct": Decimal("11.48"),
        "penalties_total": Decimal("2400.00"),
        "penalties": [],
        "cost_price": Decimal("650"),
        "cogs": Decimal("468000.00"),
        "advertising": Decimal("180000.00"),
        "advertising_pct": Decimal("8.33"),
        "ad_bonus": Decimal("60000.00"),
        "advertising_cash": Decimal("120000.00"),
        "payout_for_goods": Decimal("1440000.00"),
        "payout_net": Decimal("1189600.00"),
        "net_profit": Decimal("601600.00"),
        "net_profit_pct": Decimal("27.85"),
        "roi_pct": Decimal("128.55"),
    }
    values.update(overrides)
    return PnlSkuRow(**values)


def _dashboard(**overrides: Any) -> PnlDashboard:
    """A minimal exclusion-aware dashboard for the stub response."""
    values: dict[str, Any] = {
        "sales": Decimal("2160000.00"),
        "paid": Decimal("1800000.00"),
        "sold_units": 800,
        "returned_units": 80,
        "return_rate_pct": Decimal("10.00"),
        "logistics": Decimal("248000.00"),
        "logistics_pct": Decimal("11.48"),
        "cogs": Decimal("468000.00"),
        "uncosted_count": 0,
        "payout_net": Decimal("1189600.00"),
        "other_deductions": Decimal("165000.00"),
        "advertising": Decimal("165000.00"),
        "excluded_count": 0,
    }
    values.update(overrides)
    return PnlDashboard(**values)


class _StubSkuReportService:
    """Records what the route resolves and hands in."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def get_report(self, **kwargs: Any) -> PnlSkuReportResponse:
        """Echo the resolved inputs back through a canned report."""
        self.calls.append(kwargs)
        return PnlSkuReportResponse(
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            currency="KGS",
            rows=[_row()],
            unallocated=None,
            totals=_row(sa_name="Total"),
            dashboard=_dashboard(),
            notes=[],
        )

    async def set_exclusion(self, **kwargs: Any) -> None:
        """Record an exclusion toggle without touching a database."""
        self.calls.append({"set_exclusion": kwargs})

    async def get_sizes(self, **kwargs: Any) -> PnlSizesResponse:
        """Record the drill-down's inputs and answer with an empty size cut."""
        self.calls.append({"get_sizes": kwargs})
        return PnlSizesResponse(
            nm_id=kwargs["nm_id"],
            sa_name="M-LNX02-SND",
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            currency="KGS",
            rows=build_size_rows([]),
        )


@pytest.fixture
def sku_report() -> _StubSkuReportService:
    """The stub report service the route is wired to."""
    return _StubSkuReportService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    sku_report: _StubSkuReportService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire identity, tenancy, the stub service and the contract loaders."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_sku_report_service, sku_report)

    async def _orders(session: Any, **_kw: Any) -> dict[int, int]:
        return {NM_ID: 2600}

    async def _buyouts(session: Any, **_kw: Any) -> dict[int, tuple[int, int]]:
        return {}

    async def _ads(session: Any, **_kw: Any) -> dict[int, Decimal]:
        return {NM_ID: Decimal("180000.00")}

    async def _funnel_span(session: Any, **_kw: Any) -> tuple[date, date]:
        return (date(2026, 8, 3), date(2026, 8, 30))

    async def _ad_span(session: Any, **_kw: Any) -> tuple[date, date]:
        return (date(2026, 8, 3), date(2026, 8, 30))

    async def _bonus(session: Any, **_kw: Any) -> dict[int, Decimal]:
        return {NM_ID: Decimal("60000.00")}

    async def _bonus_span(session: Any, **_kw: Any) -> tuple[date, date]:
        return (date(2026, 8, 3), date(2026, 8, 30))

    async def _unknown_funding(session: Any, **_kw: Any) -> list[str]:
        return []

    async def _bonus_currencies(session: Any, **_kw: Any) -> list[str]:
        return ["KGS"]

    async def _photos(session: Any, **_kw: Any) -> dict[int, str]:
        return {NM_ID: PHOTO_URL}

    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_orders_by_nm", _orders)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_buyouts_by_nm", _buyouts)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_ad_spend_by_nm", _ads)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.funnel_coverage", _funnel_span)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.ad_coverage", _ad_span)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_card_photos", _photos)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_ad_bonus_by_nm", _bonus)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.ad_bonus_coverage", _bonus_span)
    monkeypatch.setattr(
        "src.modules.finreports.routers.pnl.ad_bonus_unknown_types", _unknown_funding
    )


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_report_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sku_report: _StubSkuReportService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the report."""
    response = await client.get("/api/v1/finreports/pnl/skus", headers=headers)

    assert response.status_code == 200
    assert sku_report.calls[0]["workspace_id"] == workspace.id


async def test_an_arbitrary_window_is_passed_through_verbatim(
    client: httpx.AsyncClient, headers: dict[str, str], sku_report: _StubSkuReportService
) -> None:
    """Any start/end pair is a valid period — not only report weeks."""
    await client.get(
        "/api/v1/finreports/pnl/skus",
        params={"date_from": "2025-03-04", "date_to": "2025-11-17"},
        headers=headers,
    )

    assert sku_report.calls[0]["date_from"] == date(2025, 3, 4)
    assert sku_report.calls[0]["date_to"] == date(2025, 11, 17)


async def test_an_omitted_window_defaults_to_the_last_four_weeks(
    client: httpx.AsyncClient, headers: dict[str, str], sku_report: _StubSkuReportService
) -> None:
    """No dates means the last 28 settlement days, ending on the Moscow day."""
    await client.get("/api/v1/finreports/pnl/skus", headers=headers)

    call = sku_report.calls[0]
    assert call["date_to"] == moscow_today()
    assert call["date_from"] == moscow_today() - timedelta(days=DEFAULT_WINDOW_DAYS)


async def test_the_monitoring_figures_reach_the_service_through_the_route(
    client: httpx.AsyncClient, headers: dict[str, str], sku_report: _StubSkuReportService
) -> None:
    """Orders and ad spend are resolved via the monitoring contract, not inside
    the service — the service stays module-pure and unit-testable."""
    await client.get("/api/v1/finreports/pnl/skus", headers=headers)

    call = sku_report.calls[0]
    assert call["orders"] == {NM_ID: 2600}
    assert call["ad_spend"] == {NM_ID: Decimal("180000.00")}
    assert call["funnel_span"] == (date(2026, 8, 3), date(2026, 8, 30))
    assert call["ad_span"] == (date(2026, 8, 3), date(2026, 8, 30))


async def test_the_response_serialises_the_row_shape_the_table_reads(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The wire shape is the frontend contract — pin the field names."""
    response = await client.get("/api/v1/finreports/pnl/skus", headers=headers)

    row = response.json()["rows"][0]
    for field in (
        "subject_name",
        "brand_name",
        "is_excluded",
        "average_cheque",
        "roi_pct",
        "buyout_pct",
        "orders_units",
        "sold_units",
        "return_rate_pct",
        "sales_amount",
        "revenue_paid",
        "spp_pct",
        "logistics_total",
        "logistics_pct",
        "penalties",
        "cogs",
        "advertising",
        "payout_net",
        "net_profit",
    ):
        assert field in row


async def test_a_missing_workspace_header_is_rejected(client: httpx.AsyncClient, user: Any) -> None:
    """Without a workspace there is no tenancy scope — the read must not run."""
    response = await client.get("/api/v1/finreports/pnl/skus", headers=auth_headers(user.id))

    assert response.status_code in (400, 422)


async def test_the_response_carries_the_exclusion_aware_dashboard(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The five cards read from `dashboard`, not `totals` — pin its shape."""
    response = await client.get("/api/v1/finreports/pnl/skus", headers=headers)

    dashboard = response.json()["dashboard"]
    for field in (
        "sales",
        "paid",
        "logistics",
        "cogs",
        "payout_net",
        "other_deductions",
        "advertising",
        "excluded_count",
    ):
        assert field in dashboard


async def test_marking_a_sku_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sku_report: _StubSkuReportService,
    workspace: Workspace,
) -> None:
    """The "Exclude from total" mark persists against the header's workspace."""
    response = await client.put(
        f"/api/v1/finreports/pnl/skus/{NM_ID}/exclusion",
        json={"excluded": True},
        headers=headers,
    )

    assert response.status_code == 204
    call = sku_report.calls[0]["set_exclusion"]
    assert call == {"workspace_id": workspace.id, "nm_id": NM_ID, "excluded": True}


async def test_marking_a_sku_needs_a_workspace(client: httpx.AsyncClient, user: Any) -> None:
    """No tenancy scope, no write — the mark must not run headerless."""
    response = await client.put(
        f"/api/v1/finreports/pnl/skus/{NM_ID}/exclusion",
        json={"excluded": True},
        headers=auth_headers(user.id),
    )

    assert response.status_code in (400, 422)


async def test_the_size_drill_down_is_scoped_to_the_active_workspace_and_window(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sku_report: _StubSkuReportService,
    workspace: Workspace,
) -> None:
    """The route hands the service the caller's workspace, the article and the window.

    The article id comes from the URL, so the workspace has to come from the
    header and nowhere else: an id from another seller must return that
    seller's nothing, never their rows.
    """
    response = await client.get(
        f"/api/v1/finreports/pnl/skus/{NM_ID}/sizes",
        params={"date_from": "2026-09-01", "date_to": "2026-09-21"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["nm_id"] == NM_ID
    assert sku_report.calls[-1] == {
        "get_sizes": {
            "workspace_id": workspace.id,
            "nm_id": NM_ID,
            "date_from": date(2026, 9, 1),
            "date_to": date(2026, 9, 21),
        }
    }


async def test_the_size_drill_down_needs_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """Without a workspace the route refuses rather than guessing one."""
    response = await client.get(
        f"/api/v1/finreports/pnl/skus/{NM_ID}/sizes", headers=auth_headers(user.id)
    )

    assert response.status_code == 400
