"""Component tests for the finreports period list (``GET /finreports/weeks``).

The P&L's period picker is built from this answer, so what is proved here is
the transport contract around it: the caller's active workspace scopes the
read, and a request without one is refused rather than answered for somebody.
The statement's own routes are in ``test_pnl_routes.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest

from src.modules.finreports.deps import get_period_service
from src.modules.finreports.schemas import WeekPeriod, WeeksResponse
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubPeriodService:
    """Records the workspace each request resolves."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def list_weeks(self, **kwargs: Any) -> WeeksResponse:
        """Return one harvested week."""
        self.calls.append(kwargs)
        return WeeksResponse(
            weeks=[WeekPeriod(report_id=1, date_from=date(2026, 6, 1), date_to=date(2026, 6, 7))]
        )


@pytest.fixture
def periods() -> _StubPeriodService:
    """The stub period service the route is wired to."""
    return _StubPeriodService()


@pytest.fixture(autouse=True)
def _wire_finreports(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    periods: _StubPeriodService,
) -> None:
    """Wire identity, tenancy and the stubbed period service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_period_service, periods)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_weeks_are_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    periods: _StubPeriodService,
    workspace: Workspace,
) -> None:
    """The week selector lists only the caller's own harvested reports."""
    response = await client.get("/api/v1/finreports/weeks", headers=headers)

    assert response.status_code == 200
    assert response.json()["weeks"][0]["report_id"] == 1
    assert periods.calls[0]["workspace_id"] == workspace.id


async def test_finreports_requires_the_workspace_header(
    client: httpx.AsyncClient, user: Any
) -> None:
    """Settlement periods are tenant data; no header means no read."""
    response = await client.get("/api/v1/finreports/weeks", headers=auth_headers(user.id))

    assert response.status_code == 400
