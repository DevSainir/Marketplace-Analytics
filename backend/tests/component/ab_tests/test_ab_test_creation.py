"""Component tests for configuring a test — the two mutually exclusive triggers.

Split from the route tests when the file passed the 500-line ceiling. These
cases are about what a *configuration* is allowed to be; the others are about
how the routes behave once one exists.
"""

from __future__ import annotations

import httpx

from src.core.exceptions import ConflictError
from src.core.exceptions import ValidationError as DomainValidationError
from tests.component.ab_tests.conftest import NM_ID, TEST_ID, _StubCatalog


async def test_the_two_triggers_are_mutually_exclusive(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Sending the other mode's setting is refused, not silently ignored.

    A test that rotated on "10 000 impressions or 2 hours, whichever first"
    would measure its variants over different exposures, which is the one thing
    a budget exists to prevent. Dropping the extra field quietly would leave the
    user believing they had configured something they had not.
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
    """The exclusivity holds on edit, not just on create.

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
