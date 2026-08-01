"""Component tests for the cost-price Excel round-trip HTTP surface.

The workbook building and parsing are proved in ``tests/unit/finreports``; what
is proved here is the transport — that the export streams an ``.xlsx`` with the
download headers a browser needs, that the import accepts a multipart upload and
returns the service's summary, that an empty file is refused before the parser
ever sees it, and — carrying the most weight — that both routes are scoped to the
caller's workspace, because a cost price is the seller's own commercial data.

The export now serves the per-SKU P&L, so it is wired like ``GET /pnl/skus``: a
stub :class:`SkuReportService` plus monkeypatched monitoring loaders. The import
still writes through :class:`CostPriceService`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_cost_price_service, get_sku_report_service
from src.modules.finreports.schemas import CostPriceImportIssue, CostPriceImportResponse
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _StubSkuReportService:
    """Records the export scope; hands back placeholder workbook bytes."""

    def __init__(self) -> None:
        """Start with nothing exported."""
        self.exported: list[dict[str, Any]] = []

    async def export_workbook(self, **kwargs: Any) -> bytes:
        """Record the scope (window + workspace) and return canned bytes."""
        self.exported.append(kwargs)
        return b"XLSX-BYTES"


class _StubCostPriceService:
    """Records every upload and reports a summary with one skipped row."""

    def __init__(self) -> None:
        """Start with nothing imported."""
        self.imported: list[dict[str, Any]] = []

    async def import_workbook(self, **kwargs: Any) -> CostPriceImportResponse:
        """Record the upload (filename + bytes + workspace) and report a summary."""
        self.imported.append(kwargs)
        return CostPriceImportResponse(
            applied=1,
            skipped=2,
            issues=[CostPriceImportIssue(row=5, nm_id=999, reason="SKU не продавался.")],
        )


@pytest.fixture
def sku_report() -> _StubSkuReportService:
    """The stub report service the export route is wired to."""
    return _StubSkuReportService()


@pytest.fixture
def costs() -> _StubCostPriceService:
    """The stub cost-price service the import route is wired to."""
    return _StubCostPriceService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    sku_report: _StubSkuReportService,
    costs: _StubCostPriceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire identity, tenancy, both stub services and the contract loaders."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_sku_report_service, sku_report)
    override(get_cost_price_service, costs)

    async def _orders(session: Any, **_kw: Any) -> dict[int, int]:
        return {}

    async def _ads(session: Any, **_kw: Any) -> dict[int, Decimal]:
        return {}

    async def _span(session: Any, **_kw: Any) -> tuple[date, date]:
        return (date(2024, 1, 1), date(2026, 1, 1))

    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_orders_by_nm", _orders)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.load_ad_spend_by_nm", _ads)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.funnel_coverage", _span)
    monkeypatch.setattr("src.modules.finreports.routers.pnl.ad_coverage", _span)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_export_streams_an_xlsx_scoped_to_the_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    sku_report: _StubSkuReportService,
    workspace: Workspace,
) -> None:
    """The P&L downloads as an .xlsx built for the caller's own workspace."""
    response = await client.get("/api/v1/finreports/cost-prices/export", headers=headers)

    assert response.status_code == 200
    assert response.content == b"XLSX-BYTES"
    assert response.headers["content-type"] == _XLSX_MEDIA_TYPE
    assert "attachment" in response.headers["content-disposition"]
    assert sku_report.exported[0]["workspace_id"] == workspace.id


async def test_the_export_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """No tenancy, no export — it would otherwise be one seller's figures."""
    response = await client.get(
        "/api/v1/finreports/cost-prices/export", headers=auth_headers(user.id)
    )

    assert response.status_code in {400, 422}


async def test_an_uploaded_sheet_reaches_the_service_scoped_to_the_caller(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    costs: _StubCostPriceService,
    workspace: Workspace,
) -> None:
    """The multipart upload reaches the service with its name, bytes and a summary back."""
    response = await client.post(
        "/api/v1/finreports/cost-prices/import",
        files={"file": ("pnl.xlsx", b"PK\x03\x04 fake", "application/octet-stream")},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == 1
    assert body["skipped"] == 2
    assert body["issues"][0]["nm_id"] == 999
    assert costs.imported[0]["workspace_id"] == workspace.id
    assert costs.imported[0]["filename"] == "pnl.xlsx"
    assert costs.imported[0]["data"] == b"PK\x03\x04 fake"


async def test_an_empty_upload_is_rejected_before_parsing(
    client: httpx.AsyncClient, headers: dict[str, str], costs: _StubCostPriceService
) -> None:
    """An empty file is a 422, and the service is never asked to parse it."""
    response = await client.post(
        "/api/v1/finreports/cost-prices/import",
        files={"file": ("pnl.xlsx", b"", "application/octet-stream")},
        headers=headers,
    )

    assert response.status_code == 422
    assert costs.imported == []


async def test_the_import_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """A write to cost prices must be tenanted like every other."""
    response = await client.post(
        "/api/v1/finreports/cost-prices/import",
        files={"file": ("pnl.xlsx", b"PK\x03\x04", "application/octet-stream")},
        headers=auth_headers(user.id),
    )

    assert response.status_code in {400, 422}
