"""Who may read a кабинет's history-backfill progress, through the route as mounted.

The progress strip is the answer to «почему тут пусто», so it is a member's
read, not an owner's. From 2026-09-10 to 2026-10-17 the route's path binder was
the owner-only one and every manager got 403 — the SPA swallowed it and drew
nothing. These tests hold the member rule (own organisation, or a head's grant)
and its limit (anyone else reads the кабинет as missing).

The owner-only path routes keep refusing a manager: that is
``test_administration_requires_the_owner_role`` in ``test_workspace_admin.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.organizations.contract import EffectiveRole, SubscriptionState
from src.modules.workspaces.deps import get_workspace_guest_repo
from src.modules.workspaces.models import Workspace
from src.modules.workspaces.schemas import BackfillLaneStatus, BackfillStatusResponse
from tests.support.auth import auth_headers
from tests.support.fakes import FakeWorkspaceRepository, make_workspace

#: What the stubbed reader answers: one lane still walking.
_PROGRESS = BackfillStatusResponse(
    active=True,
    lanes=[
        BackfillLaneStatus(
            lane="funnel",
            label="Воронка",
            state="running",
            done_units=30,
            total_units=180,
            percent=17,
            message="Загружаем историю воронки.",
        )
    ],
)


class _FakeGuestRepository:
    """The heads' grants, as ``(workspace_id, user_id)`` pairs."""

    def __init__(self, grants: set[tuple[uuid.UUID, uuid.UUID]]) -> None:
        """Seed the grants."""
        self.grants = grants

    async def exists(self, *, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Whether this person holds a grant on this workspace."""
        return (workspace_id, user_id) in self.grants


@pytest.fixture
def read_for(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Stub the progress reader and record which workspace it was asked about.

    Patched at the router module: the reader is a plain function over the
    request session, which this tier replaces with a tripwire.
    """
    asked: list[uuid.UUID] = []

    async def _read_progress(_session: Any, workspace_id: uuid.UUID) -> BackfillStatusResponse:
        asked.append(workspace_id)
        return _PROGRESS

    monkeypatch.setattr("src.modules.workspaces.routers.read_progress", _read_progress)
    return asked


@pytest.fixture
def foreign_workspace(
    foreign_organization_id: uuid.UUID, workspace_repo: FakeWorkspaceRepository
) -> Workspace:
    """Another company's кабинет, known to the workspace store."""
    ws = make_workspace(organization_id=foreign_organization_id, name="NEVA")
    workspace_repo.workspaces[ws.id] = ws
    return ws


def _url(workspace_id: uuid.UUID) -> str:
    return f"/api/v1/workspaces/{workspace_id}/backfill"


async def test_a_manager_sees_the_backfill_progress(
    client: httpx.AsyncClient,
    authenticated: None,
    login_as: Callable[..., None],
    user: Any,
    workspace: Workspace,
    read_for: list[uuid.UUID],
) -> None:
    """A read-only manager gets the strip, not the 403 that left the page blank."""
    # Arrange
    login_as(role=EffectiveRole.MANAGER)

    # Act
    response = await client.get(_url(workspace.id), headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 200
    assert response.json()["lanes"][0]["percent"] == 17
    assert read_for == [workspace.id]


async def test_a_head_with_a_grant_sees_the_foreign_backfill_progress(
    client: httpx.AsyncClient,
    authenticated: None,
    login_as: Callable[..., None],
    override: Callable[[Any, Any], None],
    user: Any,
    foreign_workspace: Workspace,
    read_for: list[uuid.UUID],
) -> None:
    """A head may read the strip in a кабинет granted to them, as any page there."""
    # Arrange
    login_as(
        role=EffectiveRole.USER, org=None, subscription=SubscriptionState.EXPIRED, is_head=True
    )
    override(get_workspace_guest_repo, _FakeGuestRepository({(foreign_workspace.id, user.id)}))

    # Act
    response = await client.get(_url(foreign_workspace.id), headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 200
    assert read_for == [foreign_workspace.id]


async def test_a_member_of_another_organisation_gets_404(
    client: httpx.AsyncClient,
    authenticated: None,
    login_as: Callable[..., None],
    foreign_organization_id: uuid.UUID,
    user: Any,
    workspace: Workspace,
    read_for: list[uuid.UUID],
) -> None:
    """Another company's кабинет reads as missing, never as forbidden.

    A 403 would confirm the id names a real workspace — an oracle for other
    sellers' ids, which guard every other route.
    """
    # Arrange
    login_as(role=EffectiveRole.OWNER, org=foreign_organization_id)

    # Act
    response = await client.get(_url(workspace.id), headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 404
    assert read_for == []


async def test_a_head_without_a_grant_gets_404(
    client: httpx.AsyncClient,
    authenticated: None,
    login_as: Callable[..., None],
    override: Callable[[Any, Any], None],
    user: Any,
    foreign_workspace: Workspace,
    read_for: list[uuid.UUID],
) -> None:
    """The head role alone opens no other company's кабинет."""
    # Arrange
    login_as(is_head=True)
    override(get_workspace_guest_repo, _FakeGuestRepository(set()))

    # Act
    response = await client.get(_url(foreign_workspace.id), headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 404
    assert read_for == []


async def test_an_unknown_workspace_gets_404(
    client: httpx.AsyncClient,
    authenticated: None,
    user: Any,
    read_for: list[uuid.UUID],
) -> None:
    """A deleted кабинет still selected in the SPA is 404, the same as a foreign one."""
    # Act
    response = await client.get(_url(uuid.uuid4()), headers=auth_headers(user.id))

    # Assert
    assert response.status_code == 404
    assert read_for == []
