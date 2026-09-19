"""Component tests for configuring a test — which bounds each mode accepts.

Split from the route tests when the file passed the 500-line ceiling. These
cases are about what a *configuration* is allowed to be; the others are about
how the routes behave once one exists.
"""

from __future__ import annotations

import httpx

from src.core.exceptions import ConflictError
from src.core.exceptions import ValidationError as DomainValidationError
from tests.component.ab_tests.conftest import CARD, NM_ID, TEST_ID, _StubCatalog, _StubCatalogue


async def test_a_single_bound_mode_refuses_the_other_bound(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Sending a setting the mode will not read is refused, not silently ignored.

    Dropping it quietly would leave the user believing they had configured
    something they had not. The mode that reads both is «either», and it is
    tested below.
    """
    by_impressions = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={"nm_id": NM_ID, "name": "Тест", "trigger_mode": "impressions", "slot_minutes": 30},
    )
    by_time = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={
            "nm_id": NM_ID,
            "name": "Тест",
            "trigger_mode": "time",
            "impression_budget": 5000,
        },
    )

    assert by_impressions.status_code == 422
    assert by_time.status_code == 422


async def test_each_trigger_is_accepted_on_its_own(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """Either mode alone is a valid configuration and reaches the service."""
    impressions = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={
            "nm_id": NM_ID,
            "name": "Тест",
            "trigger_mode": "impressions",
            "impression_budget": 2000,
        },
    )
    timed = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={"nm_id": NM_ID, "name": "Тест", "trigger_mode": "time", "slot_minutes": 30},
    )

    assert (impressions.status_code, timed.status_code) == (201, 201)
    payloads = [call[1]["payload"] for call in catalog.calls if call[0] == "create_test"]
    assert payloads[0].impression_budget == 2000
    assert payloads[1].slot_minutes == 30


async def test_both_bounds_are_accepted_together_in_either_mode(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """«Показы и время» takes both, because the rotation reads both.

    The turn ends at whichever arrives first — 1 000 показов on a card the
    advertising is pushing, twenty minutes on one it is not.
    """
    response = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={
            "nm_id": NM_ID,
            "name": "Тест",
            "trigger_mode": "either",
            "impression_budget": 1000,
            "slot_minutes": 20,
        },
    )

    assert response.status_code == 201
    payload = next(call[1]["payload"] for call in catalog.calls if call[0] == "create_test")
    assert (payload.impression_budget, payload.slot_minutes) == (1000, 20)


async def test_creating_a_test_validates_the_article(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A non-positive nmID is rejected before any work is done."""
    response = await client.post(
        "/api/ab-tests", headers=headers, json={"nm_id": 0, "name": "Тест"}
    )

    assert response.status_code == 422


async def test_the_trigger_can_be_changed_on_an_existing_test(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """The settings PATCH reaches the service with only the fields sent.

    Editing a running test is the point of the route: the budget worth setting
    is the one chosen after seeing how fast the card actually gathers
    impressions.
    """
    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}",
        headers=headers,
        json={"trigger_mode": "time", "slot_minutes": 30},
    )

    assert response.status_code == 200
    payload = next(call[1]["payload"] for call in catalog.calls if call[0] == "update_settings")
    assert payload.slot_minutes == 30
    assert payload.impression_budget is None


async def test_a_settings_patch_needs_no_wb_token(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """Changing a number does not touch the card, so it must not need a token.

    The start route depends on the WB installer; hanging that dependency on
    this route too would stop a workspace without stored credentials from even
    renaming a test.
    """
    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}", headers=headers, json={"name": "Новое название"}
    )

    assert response.status_code == 200
    assert any(call[0] == "update_settings" for call in catalog.calls)


async def test_a_finished_test_refuses_a_settings_change(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """A completed test's settings are the record of how its results were made."""
    catalog.error = ConflictError("Настройки завершённого теста менять нельзя.")

    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}", headers=headers, json={"impression_budget": 2000}
    )

    assert response.status_code == 409


async def test_the_patch_rejects_a_setting_from_the_other_mode(
    client: httpx.AsyncClient, headers: dict[str, str], catalog: _StubCatalog
) -> None:
    """The bound rule holds on edit, not just on create.

    The service resolves the mode from the stored test when the body does not
    name one, so this refusal can only come from there — which is why the case
    is worth a route test rather than only a unit one.
    """
    catalog.error = DomainValidationError(
        "В режиме «по показам» время на вариант не задаётся — уберите slot_minutes."
    )

    response = await client.patch(
        f"/api/ab-tests/{TEST_ID}", headers=headers, json={"slot_minutes": 30}
    )

    assert response.status_code == 422


async def test_an_unknown_article_reaches_the_service_as_no_card(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    catalog: _StubCatalog,
    catalogue: _StubCatalogue,
) -> None:
    """The route resolves the article and hands the answer down, `None` included.

    The refusal itself is the service's, and is pinned against a real database
    in `tests/integration/ab_tests/test_ab_test_creation_row.py` — a stubbed
    service cannot demonstrate a rule it does not implement. What belongs here
    is the wiring: that the route looks the article up at all, which it did not
    until 2026-09-05, when `nm_id=1` was accepted straight off the body.
    """
    catalogue.card = None

    await client.post("/api/ab-tests", headers=headers, json={"nm_id": 1, "name": "Тест"})

    assert catalogue.resolved == [1]
    card = next(call[1]["card"] for call in catalog.calls if call[0] == "create_test")
    assert card is None


async def test_the_seller_article_comes_from_the_card_not_the_body(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    catalog: _StubCatalog,
) -> None:
    """The two identifiers cannot disagree, because only one of them is sent.

    The body no longer carries a vendor code at all — the list is searched by it,
    so a client-supplied value that drifted from the card would make a test
    unfindable by the article it is actually running on.
    """
    response = await client.post(
        "/api/ab-tests",
        headers=headers,
        json={"nm_id": NM_ID, "name": "Тест", "vendor_code": "ПОДДЕЛКА"},
    )

    assert response.status_code == 201
    card = next(call[1]["card"] for call in catalog.calls if call[0] == "create_test")
    assert card.vendor_code == CARD.vendor_code


async def test_the_picker_lists_the_workspaces_catalogue(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The article field is a picker, so it needs something to pick from.

    A blank query returns the first page rather than nothing, so the control
    opens with content instead of looking broken.
    """
    blank = await client.get("/api/ab-tests/skus", headers=headers)
    by_nm = await client.get("/api/ab-tests/skus", params={"q": str(NM_ID)[:5]}, headers=headers)
    by_vendor = await client.get("/api/ab-tests/skus", params={"q": "ПЛАТЬЕ"}, headers=headers)

    assert blank.status_code == 200
    assert blank.json()[0]["nm_id"] == NM_ID
    # Both identifiers reach the same card: a picker that accepted only one
    # would make typing the other read as "this SKU does not exist".
    assert by_nm.json()[0]["vendor_code"] == CARD.vendor_code
    assert by_vendor.json()[0]["nm_id"] == NM_ID


async def test_the_picker_is_not_swallowed_by_the_test_id_route(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """`/skus` is a static path competing with `/{test_id}`.

    Declared first for that reason; if the order ever flips, this asks for a
    UUID and answers 422 instead of listing the catalogue.
    """
    response = await client.get("/api/ab-tests/skus", headers=headers)

    assert response.status_code == 200
