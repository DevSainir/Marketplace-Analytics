"""Component tests for the P&L and cost-price HTTP surface.

The statement arithmetic is covered in ``tests/unit/finreports``; what is proved
here is the transport contract — that the settlement window defaults sensibly,
that the grouping is validated rather than passed through as free text, that the
caller's active workspace scopes every read *and* every write, and that a cost
price cannot be saved in a shape the P&L would then have to guess about.

The tenancy assertions carry the most weight: a cost price is the seller's own
commercial data and the statement is their revenue, so a route that resolved
either without the workspace header would leak one tenant's margins to another.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.core.timeutils import moscow_today
from src.modules.finreports.deps import get_cost_price_service, get_pnl_service
from src.modules.finreports.repos import PnlGrouping
from src.modules.finreports.schemas import (
    CostPriceItem,
    CostPriceListResponse,
    CostPriceSaveResponse,
    PnlResponse,
    PnlSection,
    PnlStatement,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 900000101

#: Matches the router's own default window.
DEFAULT_WINDOW_DAYS = 28


def _section(label: str) -> PnlSection:
    """An empty charge section (the drill-down is the repository's business)."""
    return PnlSection(label=label, amount=Decimal(0), share_pct=None, breakdown=[])


def _statement(date_from: date, date_to: date) -> PnlStatement:
    """A minimal statement that still exercises every response field.

    The figures are the synthetic week of ``tests/unit/finreports/test_pnl_statement.py``
    with 420 costed units, so the canned response is internally consistent.
    """
    return PnlStatement(
        key=None,
        label="Period total",
        date_from=date_from,
        date_to=date_to,
        currency="KGS",
        sold_units=1200,
        returned_units=150,
        net_units=1050,
        return_rate_pct=Decimal("12.50"),
        revenue_seller_price=Decimal("3168000.00"),
        wb_discount=Decimal("528000.00"),
        revenue_paid=Decimal("2640000.00"),
        average_cheque=Decimal("2514.29"),
        wb_commission=Decimal("475200.00"),
        wb_commission_vat=Decimal("79200.00"),
        wb_reward=Decimal(0),
        acquiring=Decimal("52800.00"),
        acquiring_billed_apart=Decimal(0),
        payout_from_sales=Decimal("2112000.00"),
        compensations=Decimal(0),
        payout_for_goods=Decimal("2112000.00"),
        logistics=_section("Logistics"),
        logistics_forward=Decimal("300000.00"),
        logistics_return=Decimal("60000.00"),
        logistics_unlegged=Decimal("1250.00"),
        storage=_section("Storage"),
        acceptance=Decimal(0),
        penalties=_section("Penalties"),
        deductions=_section("Deductions"),
        advertising=Decimal("156000.00"),
        additional_payments=Decimal(0),
        rebill_logistic_cost=Decimal(0),
        total_withheld=Decimal("531750.00"),
        payout_total=Decimal("1580250.00"),
        cogs=Decimal("273000.00"),
        cogs_units=420,
        cogs_coverage_pct=Decimal("40.00"),
        gross_profit=Decimal("2367000.00"),
        margin_profit=Decimal("1307250.00"),
        margin_pct=Decimal("41.26"),
        agency_vat=Decimal("540000.00"),
        settlement_rows=9600,
    )


class _StubPnlService:
    """Records the window, workspace and grouping each request resolves."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def get_statement(self, **kwargs: Any) -> PnlResponse:
        """Echo the resolved window back through a canned statement."""
        self.calls.append(kwargs)
        return PnlResponse(
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            grouping=str(kwargs["grouping"]),
            total=_statement(kwargs["date_from"], kwargs["date_to"]),
            buckets=[],
            notes=["a test caveat"],
        )


class _StubCostPriceService:
    """Records every read and write, and the workspace each was scoped to."""

    def __init__(self) -> None:
        """Start with no stored costs."""
        self.saved: list[dict[str, Any]] = []
        self.deleted: list[dict[str, Any]] = []
        self.listed: list[dict[str, Any]] = []

    async def list_cost_prices(self, **kwargs: Any) -> CostPriceListResponse:
        """Return one costed SKU and one uncosted one."""
        self.listed.append(kwargs)
        return CostPriceListResponse(
            currency="KGS",
            items=[
                CostPriceItem(
                    nm_id=NM_ID,
                    cost=Decimal("650"),
                    currency="KGS",
                    vendor_code="M-TRX01-BLK",
                    source="seed",
                    note="",
                    sold_units=720,
                )
            ],
            missing=[
                CostPriceItem(
                    nm_id=900000103,
                    cost=Decimal(0),
                    currency="",
                    vendor_code="m-lnx02-blk",
                    source="",
                    note="",
                    sold_units=480,
                )
            ],
        )

    async def save_cost_prices(self, **kwargs: Any) -> CostPriceSaveResponse:
        """Record the batch and report how many rows it carried."""
        self.saved.append(kwargs)
        return CostPriceSaveResponse(saved=len(kwargs["items"]))

    async def delete_cost_price(self, **kwargs: Any) -> int:
        """Record the removal."""
        self.deleted.append(kwargs)
        return 1


@pytest.fixture
def pnl() -> _StubPnlService:
    """The stub statement service the route is wired to."""
    return _StubPnlService()


@pytest.fixture
def costs() -> _StubCostPriceService:
    """The stub cost-price service the editor routes are wired to."""
    return _StubCostPriceService()


@pytest.fixture(autouse=True)
def _wire_pnl(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    pnl: _StubPnlService,
    costs: _StubCostPriceService,
) -> None:
    """Wire identity, tenancy and the stubbed P&L services."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_pnl_service, pnl)
    override(get_cost_price_service, costs)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_statement_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    pnl: _StubPnlService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the statement.

    One seller's revenue and margins must never be resolvable from another's
    session just because both belong to the same user.
    """
    response = await client.get("/api/v1/finreports/pnl", headers=headers)

    assert response.status_code == 200
    assert pnl.calls[0]["workspace_id"] == workspace.id


async def test_an_omitted_window_defaults_to_the_last_four_weeks(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService
) -> None:
    """No dates means the last 28 settlement days, ending on the Moscow day.

    WB dates every settlement row by the Moscow calendar, so resolving the open
    end from the host's own clock drops the most recent day for the three hours
    between 00:00 and 03:00 MSK.
    """
    await client.get("/api/v1/finreports/pnl", headers=headers)

    call = pnl.calls[0]
    assert call["date_to"] == moscow_today()
    assert call["date_from"] == moscow_today() - timedelta(days=DEFAULT_WINDOW_DAYS)


async def test_an_explicit_window_is_passed_through_verbatim(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService
) -> None:
    """The requested period reaches the service unchanged."""
    response = await client.get(
        "/api/v1/finreports/pnl",
        params={"date_from": "2026-08-10", "date_to": "2026-08-16"},
        headers=headers,
    )

    assert response.json()["total"]["payout_total"] == "1580250.00"
    assert pnl.calls[0]["date_from"] == date(2026, 8, 10)
    assert pnl.calls[0]["date_to"] == date(2026, 8, 16)


async def test_a_start_only_window_still_ends_today(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService
) -> None:
    """Half a window is completed rather than rejected."""
    await client.get("/api/v1/finreports/pnl", params={"date_from": "2026-01-01"}, headers=headers)

    assert pnl.calls[0]["date_from"] == date(2026, 1, 1)
    assert pnl.calls[0]["date_to"] == moscow_today()


async def test_malformed_dates_are_422(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    """An unparseable date must not silently fall back to the default window."""
    response = await client.get(
        "/api/v1/finreports/pnl", params={"date_from": "last-tuesday"}, headers=headers
    )

    assert response.status_code == 422


async def test_the_default_grouping_is_the_weekly_report(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService
) -> None:
    """Omitting ``grouping`` cuts the breakdown by WB's own weekly report.

    That is the period WB itself settles on, so it is the only cut whose totals
    can be checked against a document the seller already has.
    """
    await client.get("/api/v1/finreports/pnl", headers=headers)

    assert pnl.calls[0]["grouping"] is PnlGrouping.WEEK


@pytest.mark.parametrize("grouping", ["week", "month", "sku"])
async def test_every_supported_grouping_is_accepted(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService, grouping: str
) -> None:
    """The three documented cuts all resolve."""
    response = await client.get(
        "/api/v1/finreports/pnl", params={"grouping": grouping}, headers=headers
    )

    assert response.status_code == 200
    assert pnl.calls[0]["grouping"] == PnlGrouping(grouping)


async def test_an_unknown_grouping_is_422_not_a_silent_fallback(
    client: httpx.AsyncClient, headers: dict[str, str], pnl: _StubPnlService
) -> None:
    """A misspelled grouping is rejected rather than quietly answered by week.

    Answering a different question than the one asked is worse than an error on a
    financial statement — the caller has no way to tell.
    """
    response = await client.get(
        "/api/v1/finreports/pnl", params={"grouping": "quarter"}, headers=headers
    )

    assert response.status_code == 422
    assert pnl.calls == []


async def test_the_statement_carries_its_caveats(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """``notes`` travels with the figures, not separately.

    Cost coverage, unrecognised operations and unbackfilled columns each change
    how the bottom line must be read; a caller that has the number must also have
    the qualification.
    """
    response = await client.get("/api/v1/finreports/pnl", headers=headers)

    assert response.json()["notes"] == ["a test caveat"]


async def test_the_statement_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """Without ``X-Workspace-Id`` the statement is not resolvable at all."""
    response = await client.get("/api/v1/finreports/pnl", headers=auth_headers(user.id))

    assert response.status_code in {400, 422}


async def test_uncosted_skus_are_returned_alongside_the_costed_ones(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The listing names the gaps, not just the entries.

    Returning only what is on file lets a seller believe the P&L is complete when
    most of the units it settled have no cost — the ``missing`` list is what makes
    the blind spot actionable.
    """
    response = await client.get("/api/v1/finreports/cost-prices", headers=headers)

    body = response.json()
    assert [item["nm_id"] for item in body["items"]] == [NM_ID]
    assert [item["nm_id"] for item in body["missing"]] == [900000103]


async def test_saving_costs_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    costs: _StubCostPriceService,
    workspace: Workspace,
) -> None:
    """A write lands in the caller's own workspace and nowhere else."""
    response = await client.put(
        "/api/v1/finreports/cost-prices",
        json={"items": [{"nm_id": NM_ID, "cost": "650", "currency": "KGS"}]},
        headers=headers,
    )

    assert response.json() == {"saved": 1}
    assert costs.saved[0]["workspace_id"] == workspace.id


async def test_a_negative_cost_is_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """A negative cost of goods is not a business case, it is a typo.

    Accepted, it inverts the margin on every unit of that SKU ever sold.
    """
    response = await client.put(
        "/api/v1/finreports/cost-prices",
        json={"items": [{"nm_id": NM_ID, "cost": "-100"}]},
        headers=headers,
    )

    assert response.status_code == 422
    assert costs.saved == []


async def test_an_absurdly_large_cost_is_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """A slip of several extra zeros on a three-digit cost is caught at the boundary.

    Unit costs here are hundreds of KGS; 650 typed as 6500000000 would otherwise
    turn a profitable SKU into a catastrophic loss on the dashboard.
    """
    response = await client.put(
        "/api/v1/finreports/cost-prices",
        json={"items": [{"nm_id": NM_ID, "cost": "6500000000"}]},
        headers=headers,
    )

    assert response.status_code == 422
    assert costs.saved == []


async def test_the_same_sku_twice_in_one_batch_is_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """Two costs for one SKU in one save has no defensible outcome.

    PostgreSQL's ``ON CONFLICT DO UPDATE`` also refuses the batch, so without
    this the ambiguity surfaces as a 500 instead of a message.
    """
    response = await client.put(
        "/api/v1/finreports/cost-prices",
        json={"items": [{"nm_id": NM_ID, "cost": "650"}, {"nm_id": NM_ID, "cost": "540"}]},
        headers=headers,
    )

    assert response.status_code == 422
    assert costs.saved == []


async def test_an_empty_batch_is_rejected(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """Saving nothing is a client bug, not a no-op worth confirming."""
    response = await client.put(
        "/api/v1/finreports/cost-prices", json={"items": []}, headers=headers
    )

    assert response.status_code == 422
    assert costs.saved == []


async def test_a_lowercase_currency_is_normalised(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """``kgs`` is stored as ``KGS`` so it matches WB's own settlement currency.

    The statement drops costs whose currency does not match rather than
    converting them, so a case mismatch would silently uncost the SKU.
    """
    await client.put(
        "/api/v1/finreports/cost-prices",
        json={"items": [{"nm_id": NM_ID, "cost": "650", "currency": "kgs"}]},
        headers=headers,
    )

    assert costs.saved[0]["items"][0].currency == "KGS"


async def test_clearing_a_cost_is_scoped_and_returns_no_content(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    costs: _StubCostPriceService,
    workspace: Workspace,
) -> None:
    """Deleting a cost returns 204 and touches only the caller's workspace."""
    response = await client.delete(f"/api/v1/finreports/cost-prices/{NM_ID}", headers=headers)

    assert response.status_code == 204
    assert costs.deleted == [{"workspace_id": workspace.id, "nm_id": NM_ID}]


async def test_the_cost_editor_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """Cost prices are commercial data; no tenancy means no access."""
    response = await client.get("/api/v1/finreports/cost-prices", headers=auth_headers(user.id))

    assert response.status_code in {400, 422}
