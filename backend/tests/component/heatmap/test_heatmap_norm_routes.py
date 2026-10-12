"""Component tests for the heatmap's hand-set norms («Норма: ручной ввод»).

What is proved here: the norms need the monitoring grant like the page, the
кабинет from the header scopes every read and write, a read-only manager
cannot write, and the metric, the article and the value are bounded before
anything reaches the service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.heatmap.deps import get_norm_service
from src.modules.heatmap.schemas import SkuNormList, SkuNormRead
from src.modules.organizations.contract import ALL_MODULES, AccessLevel, EffectiveRole
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubNormService:
    """Records norm reads and writes."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_norms(self, **kwargs: Any) -> SkuNormList:
        """Record the list."""
        self.calls.append(("list", kwargs))
        return SkuNormList(items=[])

    async def set_norm(self, _session: Any, **kwargs: Any) -> SkuNormRead:
        """Record the set and echo the norm."""
        self.calls.append(("set", kwargs))
        return SkuNormRead(nm_id=kwargs["nm_id"], metric=kwargs["metric"], value=kwargs["value"])

    async def clear_norm(self, **kwargs: Any) -> None:
        """Record the clear."""
        self.calls.append(("clear", kwargs))


@pytest.fixture
def norms() -> _StubNormService:
    """The stub norm service the routes are wired to."""
    return _StubNormService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    norms: _StubNormService,
) -> None:
    """Wire identity, tenancy and the stubbed norm service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_norm_service, norms)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active кабинет."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/heatmap/norms"),
        ("PUT", "/api/v1/heatmap/norms/123/orders"),
        ("DELETE", "/api/v1/heatmap/norms/123/orders"),
    ],
)
async def test_norms_need_the_heatmap_grant(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    norms: _StubNormService,
    method: str,
    path: str,
) -> None:
    """The norms belong to the page, so a manager without its grant reaches none of them."""
    login_as(role=EffectiveRole.MANAGER, modules=tuple(m for m in ALL_MODULES if m != "heatmap"))
    response = await client.request(method, path, json={"value": 1}, headers=headers)

    assert response.status_code == 403
    assert norms.calls == []


async def test_the_norms_are_read_for_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """The кабинет from the header scopes the list."""
    response = await client.get("/api/v1/heatmap/norms", headers=headers)

    assert response.status_code == 200
    assert norms.calls == [("list", {"workspace_id": workspace.id})]


async def test_a_writer_sets_a_norm_in_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """Article and metric come from the path, the кабинет from the header."""
    response = await client.put(
        "/api/v1/heatmap/norms/123/orders", json={"value": 50}, headers=headers
    )

    assert response.status_code == 200
    kind, call = norms.calls[0]
    assert kind == "set"
    assert call["workspace_id"] == workspace.id
    assert (call["nm_id"], call["metric"], call["value"]) == (123, "orders", 50.0)


async def test_a_read_only_manager_cannot_set_or_clear_a_norm(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    norms: _StubNormService,
) -> None:
    """A norm changes how everyone in the кабинет sees the grid — it is a write."""
    login_as(role=EffectiveRole.MANAGER, access_level=AccessLevel.READ_ONLY)

    put = await client.put("/api/v1/heatmap/norms/123/orders", json={"value": 5}, headers=headers)
    delete = await client.delete("/api/v1/heatmap/norms/123/orders", headers=headers)

    assert (put.status_code, delete.status_code) == (403, 403)
    assert norms.calls == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/heatmap/norms/123/password_hash", {"value": 1}),
        ("/api/v1/heatmap/norms/0/orders", {"value": 1}),
        ("/api/v1/heatmap/norms/123/orders", {"value": 1e13}),
        ("/api/v1/heatmap/norms/123/orders", {"value": "NaN"}),
    ],
)
async def test_a_norm_outside_the_bounds_is_refused(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    path: str,
    body: dict[str, Any],
) -> None:
    """Metric is a closed list, the article positive, the value finite and bounded."""
    response = await client.put(path, json=body, headers=headers)

    assert response.status_code == 422
    assert norms.calls == []


async def test_clearing_a_norm_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    norms: _StubNormService,
    workspace: Workspace,
) -> None:
    """A clear can only ever reach the caller's own кабинет."""
    response = await client.delete("/api/v1/heatmap/norms/123/orders", headers=headers)

    assert response.status_code == 204
    assert norms.calls == [
        ("clear", {"workspace_id": workspace.id, "nm_id": 123, "metric": "orders"})
    ]
