"""Shared fixtures for the A/Б-tests component tests.

The stubbed catalog service, the stubbed WB installer, and the identity and
tenancy wiring every case in this directory needs. Split out when the route
tests and the configuration tests became two files.

The module is internal-only, so ``_internal_caller`` below logs every test in as
one of us; the guard itself is proved by the one test that deliberately does not.
The writing guard on top of it is proved by the read-only-manager tests at the
bottom, which are parametrised over every state-changing route.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.modules.ab_tests.deps import get_catalog_service, get_installer
from src.modules.ab_tests.schemas import AbTestDetail, AbTestRead, VariantMetrics
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

TEST_ID = uuid.UUID("00000000-0000-7000-8000-0000000000t1".replace("t", "0"))
VARIANT_ID = uuid.UUID("00000000-0000-7000-8000-00000000000a")
NM_ID = 995716075

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 1024


def _read(**overrides: Any) -> AbTestRead:
    """A list row with sane defaults."""
    payload: dict[str, Any] = {
        "id": TEST_ID,
        "nm_id": NM_ID,
        "vendor_code": "ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК",
        "name": "Тест главного фото",
        "status": "draft",
        "trigger_mode": "impressions",
        "impression_budget": 10_000,
        "slot_minutes": 60,
        "active_variant_id": None,
        "variant_count": 0,
        "started_at": None,
        "finished_at": None,
        "created_at": datetime(2026, 8, 20, tzinfo=UTC),
    }
    payload.update(overrides)
    return AbTestRead(**payload)


def _detail() -> AbTestDetail:
    """A detail payload carrying one measured photo."""
    return AbTestDetail(
        **_read(status="running", active_variant_id=VARIANT_ID, variant_count=1).model_dump(),
        variants=[
            VariantMetrics(
                variant_id=VARIANT_ID,
                position=1,
                image_url=f"/api/ab-tests/{TEST_ID}/variants/{VARIANT_ID}/image",
                is_active=True,
                click_through=Decimal("8.97"),
                add_to_cart=Decimal("8.04"),
                order_rate=Decimal("33.25"),
                views=54_249,
                clicks=4_865,
                atbs=391,
                orders=130,
                spend=Decimal("12500.00"),
                days_measured=7,
            )
        ],
    )


class _StubInstaller:
    """Stands in for the WB media upload the start route wires in."""

    def __init__(self) -> None:
        self.installed: list[int] = []

    async def install(self, *, nm_id: int, variant: Any) -> None:
        self.installed.append(nm_id)


class _StubCatalog:
    """Answers every route, recording what it was asked."""

    def __init__(self) -> None:
        """Start with benign answers and no recorded calls."""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.rows: list[AbTestRead] = [_read()]
        self.error: Exception | None = None
        self.uploaded: list[tuple[bytes, str, str]] = []

    async def list_tests(self, **kwargs: Any) -> list[AbTestRead]:
        self.calls.append(("list_tests", kwargs))
        return self.rows

    async def get_detail(self, **kwargs: Any) -> AbTestDetail:
        self.calls.append(("get_detail", kwargs))
        if self.error is not None:
            raise self.error
        return _detail()

    async def create_test(self, **kwargs: Any) -> AbTestRead:
        self.calls.append(("create_test", kwargs))
        return _read()

    async def update_settings(self, **kwargs: Any) -> AbTestRead:
        self.calls.append(("update_settings", kwargs))
        if self.error is not None:
            raise self.error
        return _read()

    async def set_status(self, **kwargs: Any) -> AbTestRead:
        self.calls.append(("set_status", kwargs))
        if self.error is not None:
            raise self.error
        return _read(status=kwargs["status"])

    async def delete_test(self, **kwargs: Any) -> None:
        self.calls.append(("delete_test", kwargs))
        if self.error is not None:
            raise self.error

    async def add_variant(self, **kwargs: Any) -> Any:
        self.calls.append(("add_variant", kwargs))
        if self.error is not None:
            raise self.error
        self.uploaded.append((kwargs["content"], kwargs["content_type"], kwargs["filename"]))
        return None

    async def delete_variant(self, **kwargs: Any) -> None:
        self.calls.append(("delete_variant", kwargs))
        if self.error is not None:
            raise self.error

    async def read_variant_image(self, **kwargs: Any) -> tuple[bytes, str]:
        self.calls.append(("read_variant_image", kwargs))
        if self.error is not None:
            raise self.error
        return JPEG, "image/jpeg"


@pytest.fixture
def catalog() -> _StubCatalog:
    """The stub service the routes are wired to."""
    return _StubCatalog()


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    catalog: _StubCatalog,
) -> None:
    """Wire identity, tenancy and the stubbed service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_catalog_service, catalog)
    override(get_installer, _StubInstaller())


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


@pytest.fixture(autouse=True)
def _internal_caller(login_as: Any) -> None:
    """Call as one of us: A/Б-тесты is not a feature customers have bought."""
    login_as(is_primary_org=True)
