"""Component tests for the finreports HTTP surface.

proved here is the transport contract around it — that the settlement-date
window defaults sensibly when the client sends none, that the caller's active
attachment rather than as JSON.

That window default matters more than it looks: this data feeds a legal claim,
so an endpoint that silently answered over "all time" instead of the requested
period would put a wrong total in a document filed with WB.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.modules.finreports.schemas import (
    WeekPeriod,
    WeeksResponse,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 953770957


    """A minimal, internally consistent totals block."""
        currency="RUB",
        logistics_billed=Decimal("278"),
        logistics_fair=Decimal("158"),
        logistics_overpay=Decimal("120"),
        total_damage=Decimal("520"),
        overpay_ratio=Decimal("1.76"),
    )


        nm_id=NM_ID,
        sa_name="M-TRX01",
        currency="RUB",
        declared_volume_l=Decimal("10"),
        volume_ratio=Decimal("2"),
        logistics_billed=Decimal("278"),
        logistics_fair=Decimal("158"),
        logistics_overpay=Decimal("120"),
        cost_ratio=Decimal("1.76"),
        total_damage=Decimal("520"),
        delivery_units=1,
        logistics_rows=1,
        has_measurement=True,
    )


    """Records the window and workspace each route resolves."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_weeks(self, **kwargs: Any) -> WeeksResponse:
        """Return one harvested week."""
        self.calls.append(("list_weeks", kwargs))
        return WeeksResponse(
            weeks=[WeekPeriod(report_id=1, date_from=date(2026, 6, 1), date_to=date(2026, 6, 7))]
        )

        """Return a one-SKU summary over the requested window."""
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            totals=_totals(),
            skus=[_sku_item()],
            notes=[],
        )


    """Returns a recognisable ZIP payload plus the download filename."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def build_package(self, **kwargs: Any) -> tuple[bytes, str]:
        """Return the archive bytes and the name it should download under."""
        self.calls.append(kwargs)


@pytest.fixture


@pytest.fixture


@pytest.fixture(autouse=True)
def _wire_finreports(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire identity, tenancy and the stubbed finreports services.

    the raw session rather than a dependency, so it is patched at the router's
    import site instead of overridden through DI.
    """
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)

    async def _workspace_name(session: Any, workspace_id: Any) -> str:
        return workspace.name

    monkeypatch.setattr(
    )


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.fixture(autouse=True)
def _internal_caller(login_as: Any) -> None:

    The guard is proved by ``test_a_customer_cannot_reach_the_claim`` below,
    which deliberately does not.
    """
    login_as(is_primary_org=True)


async def test_weeks_are_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    workspace: Workspace,
) -> None:
    """The week selector lists only the caller's own harvested reports."""
    response = await client.get("/api/v1/finreports/weeks", headers=headers)

    assert response.status_code == 200


async def test_explicit_window_is_passed_through_verbatim(
) -> None:
    """The dates the client asks for are the dates the claim is computed over."""
    response = await client.get(
        headers=headers,
    )

    assert response.status_code == 200
    assert call["date_from"] == date(2026, 1, 1)
    assert call["date_to"] == date(2026, 3, 31)


async def test_omitted_window_defaults_to_the_last_four_weeks(
) -> None:
    """No dates means the last 28 days — a bounded window, never "everything".

    An unbounded default would both scan the whole ledger and quietly put an
    all-time total into a document that names a specific period.
    """

    assert call["date_to"] - call["date_from"] == timedelta(days=28)


async def test_a_start_only_window_still_ends_today(
) -> None:
    """Half a window is completed rather than rejected."""

    assert call["date_from"] == date(2026, 1, 1)
    assert call["date_to"] == date.today()


async def test_malformed_dates_are_422(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    """An unparseable date must not silently fall back to the default window."""
    response = await client.get(
    )

    assert response.status_code == 422


async def test_sku_evidence_reports_the_requested_sku(
) -> None:
    """The path ``nm_id`` reaches the service unchanged."""

        raise AssertionError("not reached in this assertion")


    with pytest.raises(AssertionError):



) -> None:
    """The export is a binary download, not a JSON envelope.

    The response has to open in a file manager for a lawyer, so the content type
    and the ``Content-Disposition`` filename are part of the contract.
    """

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.content.startswith(b"PK")


    client: httpx.AsyncClient,
    headers: dict[str, str],
    workspace: Workspace,
) -> None:
    """The claim document is filed in the active workspace's legal name.

    Building the package under the wrong tenant's name would send a document
    naming the wrong seller to WB.
    """

    assert claim.calls[0]["seller_name"] == workspace.name
    assert claim.calls[0]["workspace_id"] == workspace.id


async def test_finreports_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:

    assert response.status_code == 400


async def test_a_customer_cannot_reach_the_claim(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Any
) -> None:

    from our settlement history and argued in docs/finreports/. Producing one
    for a customer would put an unfounded legal claim in their name.
    """
    login_as(is_primary_org=False)


    assert response.status_code == 403
