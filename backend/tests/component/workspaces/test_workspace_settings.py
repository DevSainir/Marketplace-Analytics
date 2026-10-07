"""Component tests for the кабинет's display settings — the «Промо-бонусы» switch.

The setting changes «Реклама» for everyone in the кабинет, so it is a write in
every sense that matters: a read-only manager must not flip it for the owner,
and nobody may flip it in a кабинет of another company.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.organizations.contract import AccessLevel, EffectiveRole
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository, make_workspace

URL = "/api/v1/workspaces/current/settings"


def _headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """The caller's token, in the кабинет the request is about."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.fixture(autouse=True)
def _wire_workspace_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
) -> None:
    """Serve the workspace routes from in-memory repositories."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)


async def test_a_writer_turns_the_bonus_off_for_the_whole_kabinet(
    client: httpx.AsyncClient, user: Any, workspace: Workspace, login_as: Callable[..., None]
) -> None:
    """Saved on the кабинет, so the list everyone loads comes back with it."""
    login_as(role=EffectiveRole.MANAGER)

    response = await client.patch(
        URL,
        headers=_headers(user, workspace),
        json={"ads_show_bonus": False},
    )
    listed = await client.get("/api/v1/workspaces", headers=auth_headers(user.id))

    assert response.status_code == 200
    assert response.json()["ads_show_bonus"] is False
    by_id = {item["id"]: item for item in listed.json()["items"]}
    assert by_id[str(workspace.id)]["ads_show_bonus"] is False


async def test_a_read_only_manager_cannot_change_it(
    client: httpx.AsyncClient, user: Any, workspace: Workspace, login_as: Callable[..., None]
) -> None:
    login_as(role=EffectiveRole.MANAGER, access_level=AccessLevel.READ_ONLY)

    response = await client.patch(
        URL,
        headers=_headers(user, workspace),
        json={"ads_show_bonus": False},
    )

    assert response.status_code == 403
    assert workspace.ads_show_bonus is True


async def test_another_companys_kabinet_reads_as_missing(
    client: httpx.AsyncClient,
    user: Any,
    workspace_repo: FakeWorkspaceRepository,
    foreign_organization_id: uuid.UUID,
) -> None:
    """404, not 403 — the route must not confirm that a foreign кабинет exists."""
    foreign = make_workspace(organization_id=foreign_organization_id, name="ООО Чужой")
    workspace_repo.workspaces[foreign.id] = foreign

    response = await client.patch(
        URL,
        headers=_headers(user, foreign),
        json={"ads_show_bonus": False},
    )

    assert response.status_code == 404
    assert foreign.ads_show_bonus is True


async def test_a_request_naming_no_setting_is_refused(
    client: httpx.AsyncClient, user: Any, workspace: Workspace
) -> None:
    """An empty or unknown body is a 422, never a 200 that changed nothing."""
    empty = await client.patch(URL, headers=_headers(user, workspace), json={})
    unknown = await client.patch(
        URL,
        headers=_headers(user, workspace),
        json={"ads_show_bonus": True, "search_clusters_enabled": True},
    )

    assert (empty.status_code, unknown.status_code) == (422, 422)
    assert workspace.search_clusters_enabled is False
