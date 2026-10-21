"""Component tests for ``GET /finreports/currency`` — the unit money is printed in.

The route is the one finreports surface outside the «P&L» grant, so the guard
is what these tests are about: a manager who can see only monitoring still gets
the unit for the money on that page, a bare account still gets nothing, and the
router split that made the exception did not take the grant off the P&L itself.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_pnl_service
from src.modules.organizations.contract import EffectiveRole
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubPnlService:
    """Answers the currency lookup and records which workspace it was asked about."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.asked: list[uuid.UUID] = []

    async def settlement_currency(self, *, workspace_id: uuid.UUID) -> str:
        """Return the workspace's settlement currency."""
        self.asked.append(workspace_id)
        return "KGS"


@pytest.fixture
def pnl() -> _StubPnlService:
    """The stub statement service the route is wired to."""
    return _StubPnlService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    pnl: _StubPnlService,
) -> None:
    """Wire identity, tenancy and the stubbed statement service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_pnl_service, pnl)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_the_currency_is_the_active_workspaces(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    pnl: _StubPnlService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, is the one whose unit comes back."""
    response = await client.get("/api/v1/finreports/currency", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"currency": "KGS"}
    assert pnl.asked == [workspace.id]


async def test_a_manager_without_the_pnl_grant_still_gets_the_currency(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
) -> None:
    """Monitoring prints money for managers who were never granted the P&L.

    Behind the grant, their matrix and chart would fall back to bare numbers
    for good, with nothing on the screen saying why.
    """
    login_as(role=EffectiveRole.MANAGER, modules=("monitoring",))

    response = await client.get("/api/v1/finreports/currency", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"currency": "KGS"}


async def test_the_pnl_itself_still_needs_the_grant(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
) -> None:
    """Carving the currency out of the grant left every figure behind it.

    The grant used to sit on the one finreports router; the currency route
    needed a router of its own beside it, and that split is exactly where the
    grant could have been dropped from everything else.
    """
    login_as(role=EffectiveRole.MANAGER, modules=("monitoring",))

    response = await client.get("/api/v1/finreports/pnl", headers=headers)

    assert response.status_code == 403


async def test_an_account_outside_any_organisation_gets_nothing(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    pnl: _StubPnlService,
) -> None:
    """Membership is still the floor: a bare account has no workspace to ask about."""
    login_as(org=None)

    response = await client.get("/api/v1/finreports/currency", headers=headers)

    assert response.status_code == 403
    assert pnl.asked == []
