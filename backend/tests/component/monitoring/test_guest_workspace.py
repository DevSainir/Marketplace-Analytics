"""A head reading another company's workspace — and only reading it.

The tenancy header is resolved against the caller's own organisation; the one
way past that is a dev's grant to an account holding the ``head`` role. These
tests hold both halves of the rule (role AND grant) and its limit (GET only),
through a real monitoring route, so what is proven is the guard as mounted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.organizations.contract import EffectiveRole, SubscriptionState
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_guest_repo
from src.modules.workspaces.models import Workspace
from tests.component.monitoring.conftest import _StubAnalyticsService
from tests.support.auth import auth_headers
from tests.support.fakes import FakeWorkspaceRepository, make_workspace


class FakeWorkspaceGuestRepository:
    """In-memory :class:`~src.modules.workspaces.repos.WorkspaceGuestRepository`."""

    def __init__(
        self,
        workspaces: list[Workspace] | None = None,
        grants: set[tuple[uuid.UUID, uuid.UUID]] | None = None,
    ) -> None:
        """Seed the store with ``(workspace_id, user_id)`` grants over known workspaces."""
        self.workspaces: dict[uuid.UUID, Workspace] = {ws.id: ws for ws in workspaces or []}
        self.grants: set[tuple[uuid.UUID, uuid.UUID]] = set(grants or ())

    async def exists(self, *, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether this person holds a grant on this workspace."""
        return (workspace_id, user_id) in self.grants

    async def list_workspaces_for_user(self, user_id: uuid.UUID) -> list[Workspace]:
        """The workspaces granted to one person."""
        return [self.workspaces[ws] for ws, user in sorted(self.grants) if user == user_id]


@pytest.fixture
def foreign_workspace(
    foreign_organization_id: uuid.UUID, workspace_repo: FakeWorkspaceRepository
) -> Workspace:
    """Another company's workspace, known to the workspace store."""
    ws = make_workspace(organization_id=foreign_organization_id, name="NEVA")
    workspace_repo.workspaces[ws.id] = ws
    return ws


@pytest.fixture
def guest_repo(
    override: Callable[[Any, Any], None], foreign_workspace: Workspace, user: Any
) -> FakeWorkspaceGuestRepository:
    """A grant opening the foreign workspace to the test's caller."""
    repo = FakeWorkspaceGuestRepository([foreign_workspace], {(foreign_workspace.id, user.id)})
    override(get_workspace_guest_repo, repo)
    return repo


@pytest.fixture
def foreign_headers(user: Any, foreign_workspace: Workspace) -> dict[str, str]:
    """The caller's token with the foreign workspace selected."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(foreign_workspace.id)}


async def test_a_head_with_a_grant_reads_the_foreign_workspace(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    foreign_workspace: Workspace,
    analytics: _StubAnalyticsService,
) -> None:
    """Role and grant together open the workspace, scoped to that workspace."""
    # Arrange
    login_as(is_head=True)

    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=foreign_headers)

    # Assert
    assert response.status_code == 200
    assert analytics.calls[0][1]["workspace_id"] == foreign_workspace.id


async def test_a_head_cannot_change_anything_in_the_foreign_workspace(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    analytics: _StubAnalyticsService,
) -> None:
    """A write is refused before it reaches the service, even for an owner at home."""
    # Arrange
    login_as(is_head=True)

    # Act
    response = await client.put(
        "/api/v1/monitoring/pins/order", headers=foreign_headers, json={"nm_ids": []}
    )

    # Assert
    assert response.status_code == 403
    assert analytics.calls == []


async def test_a_grant_without_the_head_role_opens_nothing(
    client: httpx.AsyncClient,
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    analytics: _StubAnalyticsService,
) -> None:
    """A stray grant on an ordinary account reads as a missing workspace."""
    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=foreign_headers)

    # Assert
    assert response.status_code == 404
    assert analytics.calls == []


async def test_the_head_role_without_a_grant_opens_nothing(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    override: Callable[[Any, Any], None],
    foreign_workspace: Workspace,
    foreign_headers: dict[str, str],
    analytics: _StubAnalyticsService,
) -> None:
    """The role is a precondition, not a pass: every other workspace stays 404."""
    # Arrange
    login_as(is_head=True)
    override(get_workspace_guest_repo, FakeWorkspaceGuestRepository([foreign_workspace]))

    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=foreign_headers)

    # Assert
    assert response.status_code == 404
    assert analytics.calls == []


async def test_the_switcher_lists_the_granted_workspace_as_a_guest(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    user: Any,
    workspace: Workspace,
    foreign_workspace: Workspace,
) -> None:
    """Own workspaces first and writable, the granted one after and flagged."""
    # Arrange
    login_as(is_head=True)

    # Act
    response = await client.get("/api/v1/workspaces", headers=auth_headers(user.id))

    # Assert
    items = {item["id"]: item["is_guest"] for item in response.json()["items"]}
    assert items[str(foreign_workspace.id)] is True
    assert items[str(workspace.id)] is False


def _login_as_guest_only(login_as: Callable[..., None]) -> None:
    """A head with no company of their own, exactly as ``resolve_access`` builds one."""
    login_as(
        role=EffectiveRole.USER,
        org=None,
        subscription=SubscriptionState.EXPIRED,
        is_head=True,
    )


async def test_a_guest_with_no_company_reads_the_granted_workspace(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    foreign_workspace: Workspace,
    analytics: _StubAnalyticsService,
) -> None:
    """No membership, no subscription of their own — the grant alone lets them look."""
    # Arrange
    _login_as_guest_only(login_as)

    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=foreign_headers)

    # Assert
    assert response.status_code == 200
    assert analytics.calls[0][1]["workspace_id"] == foreign_workspace.id


async def test_a_guest_with_no_company_cannot_change_anything(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    analytics: _StubAnalyticsService,
) -> None:
    """Let in past the membership check is not let in to write."""
    # Arrange
    _login_as_guest_only(login_as)

    # Act
    response = await client.put(
        "/api/v1/monitoring/pins/order", headers=foreign_headers, json={"nm_ids": []}
    )

    # Assert
    assert response.status_code == 403
    assert analytics.calls == []


async def test_a_guest_with_no_company_sees_nothing_ungranted(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    user: Any,
    workspace: Workspace,
    analytics: _StubAnalyticsService,
) -> None:
    """Every workspace without a grant is the same 404 as one that does not exist."""
    # Arrange
    _login_as_guest_only(login_as)
    headers = {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}

    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=headers)

    # Assert
    assert response.status_code == 404
    assert analytics.calls == []


async def test_the_switcher_of_a_guest_with_no_company_lists_only_the_grant(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    user: Any,
    foreign_workspace: Workspace,
) -> None:
    """Nothing of their own, and the granted workspace flagged as a guest's."""
    # Arrange
    _login_as_guest_only(login_as)

    # Act
    response = await client.get("/api/v1/workspaces", headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 200
    assert [(item["id"], item["is_guest"]) for item in response.json()["items"]] == [
        (str(foreign_workspace.id), True)
    ]


async def test_a_plain_account_with_no_company_is_still_refused(
    client: httpx.AsyncClient,
    login_as: Callable[..., None],
    guest_repo: FakeWorkspaceGuestRepository,
    foreign_headers: dict[str, str],
    analytics: _StubAnalyticsService,
) -> None:
    """A stray grant on an account without the head role opens nothing."""
    # Arrange
    login_as(role=EffectiveRole.USER, org=None, subscription=SubscriptionState.EXPIRED)

    # Act
    response = await client.get("/api/v1/monitoring/summary", headers=foreign_headers)

    # Assert
    assert response.status_code == 403
    assert analytics.calls == []
