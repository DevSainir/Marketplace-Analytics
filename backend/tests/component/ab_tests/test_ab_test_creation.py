"""Component tests for configuring a test — the two mutually exclusive triggers.

Split from the route tests when the file passed the 500-line ceiling. These
cases are about what a *configuration* is allowed to be; the others are about
how the routes behave once one exists.
"""

from __future__ import annotations

import httpx

from tests.component.ab_tests.conftest import NM_ID, _StubCatalog


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
