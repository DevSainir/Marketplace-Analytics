"""The expiry ramp, seen from the monitoring HTTP surface.

Its own module because it is a different subject from "do these routes work":
these assertions are about *when a working route stops writing*, and they are
the executable statement of a product promise — that expiry is a ramp and not a
cliff. Keeping them together is what makes the pair legible: the refusals and
the grace-window write have to be read next to each other or neither means
anything."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.modules.organizations.contract import SubscriptionState
from tests.component.monitoring.conftest import NM_ID, _StubAnalyticsService


# --------------------------------------------------------------------------- #
# The expiry ramp, at the HTTP layer
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("PUT", "/api/v1/monitoring/pins/order", {"nm_ids": [NM_ID]}),
        ("PUT", f"/api/v1/monitoring/skus/{NM_ID}/pin", {"pinned": True}),
        ("PUT", f"/api/v1/monitoring/skus/{NM_ID}/pin-color", {"color": "#aabbcc"}),
        (
            "PUT",
            f"/api/v1/monitoring/skus/{NM_ID}/warehouse-marks",
            {"warehouse_name": "Коледино", "marked": True},
        ),
        ("PUT", f"/api/v1/monitoring/skus/{NM_ID}/comments/2026-09-01", {"body": "x"}),
        ("PUT", f"/api/v1/monitoring/skus/{NM_ID}/actions/2026-09-01", {}),
    ],
)
async def test_a_lapsed_workspace_past_grace_cannot_write(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    login_as: Callable[..., None],
    method: str,
    path: str,
    body: dict[str, Any],
) -> None:
    """Past the grace window every note, pin and colour stops saving.

    These routes spend no WB budget, which is why they were the ones left
    unguarded; they still write to the seller's workspace, and the rule the
    guard states is "everything that changes state", not "everything expensive".
    """
    login_as(subscription=SubscriptionState.READ_ONLY)

    response = await client.request(method, path, headers=headers, json=body)

    assert response.status_code == 403


async def test_the_grace_window_still_writes(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    analytics: _StubAnalyticsService,
    login_as: Callable[..., None],
) -> None:
    """A lapsed term inside its grace window changes nothing about writing.

    This is the soft landing the product deliberately keeps: renewal is a manual
    bank transfer between two humans in two countries, so the first days after
    expiry must behave exactly like the last days before it. A guard that
    treated «истекла» as a cliff would lock a paying customer out on the morning
    their transfer is still clearing.
    """
    login_as(subscription=SubscriptionState.GRACE)

    await client.put("/api/v1/monitoring/pins/order", headers=headers, json={"nm_ids": [NM_ID]})

    # Reaching the service at all is the assertion: what it then answers is the
    # stub's business, and a guard that had refused would never have got here.
    assert [name for name, _ in analytics.calls] == ["reorder_pins"]
