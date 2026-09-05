"""Component tests for the A/Б-tests HTTP surface.

The service's arithmetic is unit-tested; what this tier adds is the wiring —
that the routes exist where the SPA expects them, that the workspace header is
what scopes them, that an upload arrives as bytes with its content type intact,
and that the domain's refusals (a full rotation, a photo that is currently live)
reach the client as 409 rather than as a 500, and that the access ladder holds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.exceptions import ConflictError, NotFoundError
from src.modules.ab_tests.routers import router as ab_tests_router
from src.modules.organizations.contract import AccessLevel, EffectiveRole, SubscriptionState
from src.modules.workspaces.models import Workspace
from tests.component.ab_tests.conftest import JPEG, TEST_ID, VARIANT_ID, _StubCatalog


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


def _writing_routes() -> list[tuple[str, str]]:
    """Every state-changing route on the module's router, read from the router.

    Derived rather than listed because a hand-written list only ever proves the
    routes someone remembered: `PATCH /{test_id}` shipped without the guard and
    the five-entry list that preceded this could not see it. Anything that is
    not a GET has to answer for itself here.
    """
    routes = []
    for route in ab_tests_router.routes:
        methods = getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
        for method in sorted(methods - {"GET"}):
            routes.append((method, "/api" + route.path))
    return routes


@pytest.mark.parametrize(("method", "path"), _writing_routes())
async def test_every_writing_route_refuses_a_read_only_manager(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    catalog: _StubCatalog,
    login_as: Callable[..., None],
    method: str,
    path: str,
) -> None:
    """No route that changes anything may be reachable read-only.

    The assertion goes as far as the service NOT being called: a 403 that had
    still reached the catalogue would mean the refusal came after the write.
    """
    login_as(
        role=EffectiveRole.MANAGER,
        is_primary_org=True,
        access_level=AccessLevel.READ_ONLY,
    )

    response = await client.request(
        method,
        path.replace("{test_id}", str(TEST_ID)).replace("{variant_id}", str(VARIANT_ID)),
        headers=headers,
        json={},
    )

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
