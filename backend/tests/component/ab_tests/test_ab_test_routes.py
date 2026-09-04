"""Component tests for the A/Б-tests HTTP surface.

The service's arithmetic is unit-tested; what this tier adds is the wiring —
that the routes exist where the SPA expects them, that the workspace header is
what scopes them, that an upload arrives as bytes with its content type intact,
and that the domain's refusals (a full rotation, a photo that is currently live)
reach the client as 409 rather than as a 500.

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

import httpx
import pytest

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.ab_tests.deps import get_catalog_service, get_installer
from src.modules.ab_tests.schemas import AbTestDetail, AbTestRead, VariantMetrics
from src.modules.organizations.contract import AccessLevel, EffectiveRole, SubscriptionState
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
        "impression_budget": 10_000,
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


async def test_the_list_is_scoped_to_the_header_workspace(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog, workspace: Workspace
) -> None:
    """The workspace the header names is what the service is asked for.

    Tests rewrite a seller's live card, so a leak across tenants is not a
    privacy bug but a "someone changed my storefront" bug.
    """
    response = await client.get("/api/ab-tests", headers=headers)

    assert response.status_code == 200
    assert catalog.calls[0][1]["workspace_id"] == workspace.id


async def test_the_search_box_reaches_the_service(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """``?q=`` is forwarded verbatim — one box searches every field."""
    await client.get("/api/ab-tests", params={"q": "ЦВЕТОЧЕК"}, headers=headers)

    assert catalog.calls[0][1]["query"] == "ЦВЕТОЧЕК"


async def test_an_unauthenticated_caller_gets_401(client: httpx.AsyncClient) -> None:
    """The module is behind the same guard as everything else."""
    response = await client.get("/api/ab-tests")

    assert response.status_code == 401


async def test_a_foreign_test_reads_as_404(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """Another workspace's test is absent, not forbidden.

    A 403 would confirm the id exists, and a test id names a card the caller
    should not know about.
    """
    catalog.error = NotFoundError("Тест не найден.")

    response = await client.get(f"/api/ab-tests/{TEST_ID}", headers=headers)

    assert response.status_code == 404


async def test_the_detail_carries_the_result_table(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Rows are photos and columns are metrics, ratios serialised as strings."""
    response = await client.get(f"/api/ab-tests/{TEST_ID}", headers=headers)

    body = response.json()
    assert response.status_code == 200
    assert len(body["variants"]) == 1
    row = body["variants"][0]
    assert row["views"] == 54_249
    assert row["click_through"] == "8.97"
    assert row["image_url"].endswith("/image")


async def test_uploading_a_photo_passes_the_bytes_and_type_through(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """The multipart part arrives intact — bytes, MIME type and file name.

    The variant's digest is taken from these bytes, so anything the transport
    layer rewrites here breaks the link between a picture and its metrics.
    """
    response = await client.post(
        f"/api/ab-tests/{TEST_ID}/variants",
        headers=headers,
        files={"file": ("dress.jpg", JPEG, "image/jpeg")},
    )

    assert response.status_code == 201
    assert catalog.uploaded == [(JPEG, "image/jpeg", "dress.jpg")]


async def test_a_full_rotation_refuses_the_eleventh_photo_with_409(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """The ten-photo cap surfaces as a conflict, not a 500."""
    catalog.error = ConflictError("В тесте не может быть больше 10 фото.")

    response = await client.post(
        f"/api/ab-tests/{TEST_ID}/variants",
        headers=headers,
        files={"file": ("eleventh.jpg", JPEG, "image/jpeg")},
    )

    assert response.status_code == 409


async def test_the_live_photo_cannot_be_deleted(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """Removing the installed photo would leave the card pointing at nothing."""
    catalog.error = ConflictError("Нельзя удалить фото, которое сейчас стоит на карточке.")

    response = await client.delete(
        f"/api/ab-tests/{TEST_ID}/variants/{VARIANT_ID}", headers=headers
    )

    assert response.status_code == 409


async def test_the_image_route_serves_the_stored_original(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The picture comes from our own store, with its own content type.

    Not from WB's CDN: a queued variant has no WB URL yet, and a replaced one
    no longer has one.
    """
    response = await client.get(
        f"/api/ab-tests/{TEST_ID}/variants/{VARIANT_ID}/image", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == JPEG


async def test_starting_a_test_goes_through_the_status_route(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """«Запустить» is a status transition, and it reaches the service as one."""
    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}/status", headers=headers, json={"status": "running"}
    )

    assert response.status_code == 200
    assert catalog.calls[0][1]["status"] == "running"


async def test_starting_a_test_with_no_photos_is_a_409(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """An empty rotation cannot start — there is nothing to install."""
    catalog.error = ConflictError("Загрузите хотя бы одно фото, прежде чем запускать тест.")

    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}/status", headers=headers, json={"status": "running"}
    )

    assert response.status_code == 409


async def test_creating_a_test_validates_the_article(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A non-positive nmID is rejected before any work is done."""
    response = await client.post(
        "/api/ab-tests", headers=headers, json={"nm_id": 0, "name": "Тест"}
    )

    assert response.status_code == 422


async def test_a_customer_cannot_reach_ab_tests(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Any
) -> None:
    """An ordinary tenant gets 403, not a list of tests.

    A/Б-тесты installs photos on a live WB card through the Content API and was
    built against our own catalogue — it is not part of what a subscription
    buys. The guard sits on the router, so one route standing in for the module
    is the honest scope for this assertion.
    """
    login_as(is_primary_org=False)

    response = await client.get("/api/ab-tests", headers=headers)

    assert response.status_code == 403


async def test_a_read_only_manager_of_ours_still_reads_the_results(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Callable[..., None]
) -> None:
    """Read-only means read-only, not shut out.

    The owner grants A/Б-тесты at ``read_only`` precisely so someone can watch
    the rotation without touching the card; a guard that took the results table
    away with the upload button would make that grant useless.
    """
    login_as(
        role=EffectiveRole.MANAGER,
        is_primary_org=True,
        access_level=AccessLevel.READ_ONLY,
    )

    response = await client.get("/api/ab-tests", headers=headers)

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/ab-tests"),
        ("PATCH", f"/api/ab-tests/{TEST_ID}/status"),
        ("DELETE", f"/api/ab-tests/{TEST_ID}"),
        ("POST", f"/api/ab-tests/{TEST_ID}/variants"),
        ("DELETE", f"/api/ab-tests/{TEST_ID}/variants/{VARIANT_ID}"),
    ],
)
async def test_a_read_only_manager_of_ours_changes_nothing(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    catalog: _StubCatalog,
    login_as: Callable[..., None],
    method: str,
    path: str,
) -> None:
    """Every state-changing route refuses a read-only manager.

    Parametrised over all five rather than a representative one because the
    guard is declared per route here — the router-level dependency is the
    reachability guard, not this one — so a sixth writing route added without
    it would be invisible to a single-route test.

    The assertion goes as far as the service NOT being called: a 403 that still
    reached the catalogue would mean the refusal came after the write.
    """
    login_as(
        role=EffectiveRole.MANAGER,
        is_primary_org=True,
        access_level=AccessLevel.READ_ONLY,
    )

    response = await client.request(method, path, headers=headers, json={})

    assert response.status_code == 403
    assert catalog.calls == []


async def test_a_lapsed_subscription_cannot_touch_the_card_either(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Callable[..., None]
) -> None:
    """The guard's other audience: an owner past the grace window.

    Worth its own test because the two refusals are deliberately different
    sentences — this one can be acted on by renewing, and a manager's cannot —
    and a guard that answered both with the same text would send half the
    callers to support with the wrong question.
    """
    login_as(is_primary_org=True, subscription=SubscriptionState.READ_ONLY)

    response = await client.delete(f"/api/ab-tests/{TEST_ID}", headers=headers)

    assert response.status_code == 403
    assert "Продлите подписку" in response.text


async def test_the_grace_window_still_installs_photos(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    catalog: _StubCatalog,
    login_as: Callable[..., None],
) -> None:
    """Expiry is a ramp, not a cliff, and this route is on the ramp too.

    Pinned here as well as in monitoring because a rotation half-way through is
    the worst possible thing to freeze on a technicality: the card is left
    wearing whichever photo happened to be up, and the arms stop being
    comparable. The grace days exist so a clearing bank transfer cannot do that.
    """
    login_as(is_primary_org=True, subscription=SubscriptionState.GRACE)

    response = await client.delete(f"/api/ab-tests/{TEST_ID}", headers=headers)

    assert response.status_code == 204
    assert [name for name, _ in catalog.calls] == ["delete_test"]
