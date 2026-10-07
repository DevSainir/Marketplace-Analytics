"""Component tests for the «Реклама» HTTP surface.

The arithmetic is covered in ``tests/unit/advertising``; what is proved here is
the transport contract — who may reach the page while it is being built, that
the caller's active workspace scopes the read, and that the window is bounded
before it reaches a query.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.core.timeutils import moscow_today
from src.modules.advertising.deps import get_advertising_service
from src.modules.advertising.routers.advertising import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS
from src.modules.advertising.schemas import (
    AdvertisingResponse,
    AdvertisingSpan,
    AdvertisingTotals,
)
from src.modules.organizations.contract import ALL_MODULES, EffectiveRole
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubAdvertisingService:
    """Records the window and workspace each request resolves."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def span(self, _session: Any, **kwargs: Any) -> AdvertisingSpan:
        """Answer a fixed span."""
        self.calls.append(kwargs)
        return AdvertisingSpan(
            date_from=date(2026, 7, 1), date_to=date(2026, 10, 2), settled_to=date(2026, 9, 27)
        )

    async def build(self, _session: Any, **kwargs: Any) -> AdvertisingResponse:
        """Echo the resolved request back through an empty page."""
        self.calls.append(kwargs)
        return AdvertisingResponse(
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            settled_to=None,
            currency="KGS",
            ad_currencies=["KGS"],
            bonus_known=True,
            totals=AdvertisingTotals(
                spend=Decimal("100"),
                bonus=Decimal("0"),
                spend_settled=Decimal("0"),
                bonus_settled=Decimal("0"),
                sales=None,
            ),
            zones=[],
            days=[],
            skus=[],
        )


@pytest.fixture
def advertising() -> _StubAdvertisingService:
    """The stub service the routes are wired to."""
    return _StubAdvertisingService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    advertising: _StubAdvertisingService,
) -> None:
    """Wire identity, tenancy and the stubbed service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_advertising_service, advertising)


@pytest.fixture(autouse=True)
def _internal_caller(login_as: Callable[..., None]) -> None:
    """An owner in the primary organisation: the page is ours alone until it ships."""
    login_as(is_primary_org=True)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.mark.parametrize("path", ["/api/v1/advertising", "/api/v1/advertising/span"])
async def test_a_paying_customer_cannot_reach_the_page_yet(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    advertising: _StubAdvertisingService,
    path: str,
) -> None:
    """Internal-only while it is being built: its figures are unchecked on customers' кабинеты."""
    login_as(is_primary_org=False)

    response = await client.get(path, headers=headers)

    assert response.status_code == 403
    assert advertising.calls == []


async def test_a_manager_without_monitoring_cannot_reach_it(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    advertising: _StubAdvertisingService,
) -> None:
    """Advertising is «Мониторинг»'s data: without that grant the page is a 403."""
    login_as(
        role=EffectiveRole.MANAGER,
        is_primary_org=True,
        modules=tuple(m for m in ALL_MODULES if m != "monitoring"),
    )

    response = await client.get("/api/v1/advertising", headers=headers)

    assert response.status_code == 403
    assert advertising.calls == []


@pytest.mark.parametrize("path", ["/api/v1/advertising", "/api/v1/advertising/span"])
async def test_a_manager_of_ours_without_finreports_reads_the_whole_page(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    path: str,
) -> None:
    """Every member of our organisation reads it — the owner's decision of 2026-10-07.

    Three of the primary organisation's managers hold monitoring alone; the
    page, sales and ДРР included, is open to them all the same.
    """
    login_as(
        role=EffectiveRole.MANAGER,
        is_primary_org=True,
        modules=tuple(m for m in ALL_MODULES if m != "finreports"),
    )

    response = await client.get(path, headers=headers)

    assert response.status_code == 200


async def test_the_page_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    advertising: _StubAdvertisingService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the read."""
    response = await client.get("/api/v1/advertising", headers=headers)

    assert response.status_code == 200
    assert advertising.calls[0]["workspace_id"] == workspace.id


async def test_without_a_workspace_header_nothing_resolves(
    client: httpx.AsyncClient, user: Any, advertising: _StubAdvertisingService
) -> None:
    """No active workspace means no answer, not a default one."""
    response = await client.get("/api/v1/advertising", headers=auth_headers(user.id))

    assert response.status_code >= 400
    assert advertising.calls == []


async def test_an_omitted_window_is_the_last_thirty_moscow_days(
    client: httpx.AsyncClient, headers: dict[str, str], advertising: _StubAdvertisingService
) -> None:
    """No dates means thirty days ending on the MOSCOW day — the span a budget is reviewed over."""
    await client.get("/api/v1/advertising", headers=headers)

    call = advertising.calls[0]
    assert call["date_to"] == moscow_today()
    assert call["date_from"] == moscow_today() - timedelta(days=DEFAULT_WINDOW_DAYS)


async def test_a_window_longer_than_the_cap_is_refused_without_echoing_it(
    client: httpx.AsyncClient, headers: dict[str, str], advertising: _StubAdvertisingService
) -> None:
    """A two-year window is rejected before any query, and the dates are not sent back."""
    end = date(2026, 9, 6)
    start = end - timedelta(days=MAX_WINDOW_DAYS + 1)

    response = await client.get(
        "/api/v1/advertising",
        headers=headers,
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
    )

    assert response.status_code == 422
    assert start.isoformat() not in response.text
    assert advertising.calls == []


async def test_an_inverted_window_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], advertising: _StubAdvertisingService
) -> None:
    """An end before the start is a 422, not an empty page."""
    response = await client.get(
        "/api/v1/advertising",
        headers=headers,
        params={"date_from": "2026-09-10", "date_to": "2026-09-01"},
    )

    assert response.status_code == 422
    assert advertising.calls == []
