"""Component tests for the heatmap's «Группы» routes and the catalogue their editor reads.

Groups are a control on four pages — «Сводка», P&L, «Тепловая карта» and
«Реклама» — rather than a page of their own, so what is proved here is that any
one of those grants opens them, that none of the others does, and that a write
still needs the writing level on top.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.exceptions import NotFoundError
from src.modules.heatmap.deps import get_group_service, get_heatmap_service
from src.modules.heatmap.schemas import (
    HeatmapCatalogResponse,
    SkuGroupList,
    SkuGroupRead,
    SkuGroupWrite,
)
from src.modules.organizations.contract import (
    ALL_MODULES,
    GROUP_MODULES,
    AccessLevel,
    EffectiveRole,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

#: Every grant that does NOT carry the group filter.
_WITHOUT_GROUPS = tuple(m for m in ALL_MODULES if m not in {g.value for g in GROUP_MODULES})


class _StubCatalogService:
    """Records catalogue reads."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def catalog(self, _session: Any, **kwargs: Any) -> HeatmapCatalogResponse:
        """Record the catalogue read."""
        self.calls.append(kwargs)
        return HeatmapCatalogResponse(items=[], subjects=[])


class _StubGroupService:
    """Records group writes; knows one group id."""

    def __init__(self) -> None:
        """Start with one known group."""
        self.known = uuid.uuid4()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_groups(self, **kwargs: Any) -> SkuGroupList:
        """Record the list."""
        self.calls.append(("list", kwargs))
        return SkuGroupList(items=[])

    async def create(self, _session: Any, **kwargs: Any) -> SkuGroupRead:
        """Record the create and echo the group."""
        self.calls.append(("create", kwargs))
        payload: SkuGroupWrite = kwargs["payload"]
        return SkuGroupRead(id=uuid.uuid4(), name=payload.name, nm_ids=payload.nm_ids)

    async def delete(self, **kwargs: Any) -> None:
        """Delete the known group; anything else is missing."""
        self.calls.append(("delete", kwargs))
        if kwargs["group_id"] != self.known:
            raise NotFoundError("Группа не найдена.")


@pytest.fixture
def groups() -> _StubGroupService:
    """The stub group service the routes are wired to."""
    return _StubGroupService()


@pytest.fixture
def catalog() -> _StubCatalogService:
    """The stub service behind the catalogue route."""
    return _StubCatalogService()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    groups: _StubGroupService,
    catalog: _StubCatalogService,
) -> None:
    """Wire identity, tenancy and both stubbed services."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_group_service, groups)
    override(get_heatmap_service, catalog)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.mark.parametrize("page", [m.value for m in GROUP_MODULES])
@pytest.mark.parametrize("path", ["/api/v1/heatmap/groups", "/api/v1/heatmap/catalog"])
async def test_any_page_with_the_filter_opens_the_groups(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    page: str,
    path: str,
) -> None:
    """A manager holding one page with groups reads them — P&L alone included."""
    login_as(role=EffectiveRole.MANAGER, modules=(page,))

    response = await client.get(path, headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/api/v1/heatmap/groups", "/api/v1/heatmap/catalog"])
async def test_no_page_with_the_filter_no_groups(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    groups: _StubGroupService,
    catalog: _StubCatalogService,
    path: str,
) -> None:
    """«Мониторинг» and A/B tests carry no group filter, so they open nothing here."""
    login_as(role=EffectiveRole.MANAGER, modules=_WITHOUT_GROUPS)

    response = await client.get(path, headers=headers)

    assert response.status_code == 403
    assert groups.calls == []
    assert catalog.calls == []


async def test_a_writer_with_pnl_alone_creates_a_group(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    groups: _StubGroupService,
) -> None:
    """Editing follows reading: the page's grant plus the writing level is enough."""
    login_as(role=EffectiveRole.MANAGER, modules=("finreports",))

    response = await client.post(
        "/api/v1/heatmap/groups", json={"name": "Лето", "nm_ids": [1]}, headers=headers
    )

    assert response.status_code == 201
    assert [kind for kind, _ in groups.calls] == ["create"]


async def test_a_read_only_manager_cannot_create_a_group(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    groups: _StubGroupService,
) -> None:
    """A group changes what everyone in the workspace sees in the filter — it is a write."""
    login_as(role=EffectiveRole.MANAGER, access_level=AccessLevel.READ_ONLY)

    response = await client.post(
        "/api/v1/heatmap/groups",
        json={"name": "Двойки", "nm_ids": [1]},
        headers=headers,
    )

    assert response.status_code == 403
    assert groups.calls == []


async def test_a_writer_creates_a_group_in_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    groups: _StubGroupService,
    workspace: Workspace,
) -> None:
    """The workspace comes from the header; the body cannot name one."""
    response = await client.post(
        "/api/v1/heatmap/groups",
        json={"name": "  Двойки  ", "nm_ids": [1, 2]},
        headers=headers,
    )

    assert response.status_code == 201
    kind, call = groups.calls[0]
    assert kind == "create"
    assert call["workspace_id"] == workspace.id
    assert call["payload"].name == "Двойки"


async def test_a_blank_group_name_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], groups: _StubGroupService
) -> None:
    """A group the filter would list as an empty line is not a group."""
    response = await client.post(
        "/api/v1/heatmap/groups", json={"name": "   ", "nm_ids": [1]}, headers=headers
    )

    assert response.status_code == 422
    assert groups.calls == []


async def test_deleting_an_unknown_group_is_a_404(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A group of another workspace is missing, not forbidden — a guessed id confirms nothing."""
    response = await client.delete(f"/api/v1/heatmap/groups/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
