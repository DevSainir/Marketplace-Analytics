"""Component tests for workspace administration and the tenancy header.

Two guards live on this surface and both are security-relevant:

* the ``dev`` **role** gate on every mutating workspace route, and
* the ``X-Workspace-Id`` **tenancy** resolution that every data module depends
  on. Its failure modes have to be distinct (400 for a malformed header, 404
  for an unknown workspace) or the frontend cannot tell "you sent nonsense"
  from "that workspace was deleted while you had it selected".
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo, get_workspace_token_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import (
    FakeUserRepository,
    FakeWorkspaceRepository,
    FakeWorkspaceTokenRepository,
)


@pytest.fixture(autouse=True)
def _wire_workspace_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    workspace_token_repo: FakeWorkspaceTokenRepository,
    settings_override,
) -> Any:
    """Serve the workspace routes from in-memory repositories with a real key."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_workspace_token_repo, workspace_token_repo)
    with settings_override(fernet_secret_key=Fernet.generate_key().decode()):
        yield


# --------------------------------------------------------------------------- #
# Role gate
# --------------------------------------------------------------------------- #
async def test_any_authenticated_user_can_list_workspaces(
    client: httpx.AsyncClient, user: Any
) -> None:
    """Listing is open — the switcher must work for everyone."""
    response = await client.get("/api/v1/workspaces", headers=auth_headers(user.id))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("POST", "/api/v1/workspaces"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/tokens"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/tokens"),
    ],
)
async def test_administration_requires_the_dev_role(
    client: httpx.AsyncClient,
    user: Any,
    workspace: Workspace,
    method: str,
    path_template: str,
) -> None:
    """A regular account is refused with 403 on every admin route.

    These routes read and rotate WB API credentials — a plain user reaching one
    would be a real credential-exposure bug.
    """
    path = path_template.format(workspace_id=workspace.id)

    response = await client.request(method, path, headers=auth_headers(user.id), json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_dev_can_create_a_workspace(client: httpx.AsyncClient, dev_user: Any) -> None:
    """The dev role unlocks creation, answering 201 with the new workspace."""
    response = await client.post(
        "/api/v1/workspaces", headers=auth_headers(dev_user.id), json={"name": "ООО Новый"}
    )

    assert response.status_code == 201
    assert response.json()["name"] == "ООО Новый"
    assert response.json()["is_primary"] is False


async def test_duplicate_workspace_name_is_409(
    client: httpx.AsyncClient, dev_user: Any, workspace: Workspace
) -> None:
    """``ConflictError`` maps to 409 rather than a 500."""
    response = await client.post(
        "/api/v1/workspaces", headers=auth_headers(dev_user.id), json={"name": workspace.name}
    )

    assert response.status_code == 409


async def test_deleting_an_unknown_workspace_is_404(
    client: httpx.AsyncClient, dev_user: Any
) -> None:
    """``NotFoundError`` maps to 404."""
    response = await client.delete(
        f"/api/v1/workspaces/{uuid.uuid4()}", headers=auth_headers(dev_user.id)
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Token routes
# --------------------------------------------------------------------------- #
async def test_token_values_never_appear_in_a_response(
    client: httpx.AsyncClient,
    dev_user: Any,
    workspace: Workspace,
) -> None:
    """Setting a token answers with *which* kinds are configured, not their values.

    A WB token echoed back would be readable by anyone who can open the admin
    panel — and would end up in browser history, logs and error reports.
    """
    secret = "eyJhbGciOiJFUzI1NiJ9.a-real-looking-wb-token"

    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/tokens",
        headers=auth_headers(dev_user.id),
        json={"tokens": {"unified": secret}},
    )

    assert response.status_code == 200
    assert response.json()["configured"] == ["unified"]
    assert secret not in response.text


async def test_wrong_token_kind_for_the_workspace_mode_is_422(
    client: httpx.AsyncClient, dev_user: Any, workspace: Workspace
) -> None:
    """``ValidationError`` maps to 422 with the domain code, not a schema error."""
    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/tokens",
        headers=auth_headers(dev_user.id),
        json={"tokens": {"content": "a-token"}},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable_entity"


async def test_token_status_for_an_unknown_workspace_is_404(
    client: httpx.AsyncClient, dev_user: Any
) -> None:
    """A stale workspace id is a 404, never an empty "nothing configured"."""
    response = await client.get(
        f"/api/v1/workspaces/{uuid.uuid4()}/tokens", headers=auth_headers(dev_user.id)
    )

    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Tenancy header
# --------------------------------------------------------------------------- #
async def test_missing_workspace_header_is_400(client: httpx.AsyncClient, user: Any) -> None:
    """A tenant-scoped route without the header is a client error, not a 500."""
    response = await client.get("/api/v1/monitoring/summary", headers=auth_headers(user.id))

    assert response.status_code == 400
    assert WORKSPACE_HEADER in response.json()["detail"]


async def test_malformed_workspace_header_is_400(client: httpx.AsyncClient, user: Any) -> None:
    """A non-UUID header value is rejected before any query runs."""
    response = await client.get(
        "/api/v1/monitoring/summary",
        headers={**auth_headers(user.id), WORKSPACE_HEADER: "not-a-uuid"},
    )

    assert response.status_code == 400


async def test_unknown_workspace_header_is_404(client: httpx.AsyncClient, user: Any) -> None:
    """A deleted workspace still selected in the client answers 404, not 400.

    The frontend uses the distinction to clear its stored selection and prompt a
    switch instead of showing "bad request".
    """
    response = await client.get(
        "/api/v1/monitoring/summary",
        headers={**auth_headers(user.id), WORKSPACE_HEADER: str(uuid.uuid4())},
    )

    assert response.status_code == 404


async def test_tenancy_is_checked_after_authentication(client: httpx.AsyncClient) -> None:
    """An anonymous caller gets 401 even with a valid workspace header.

    Validating the header first would let an unauthenticated probe discover
    which workspace ids exist.
    """
    response = await client.get(
        "/api/v1/monitoring/summary", headers={WORKSPACE_HEADER: str(uuid.uuid4())}
    )

    assert response.status_code == 401
