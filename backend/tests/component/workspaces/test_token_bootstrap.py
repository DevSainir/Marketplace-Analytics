"""Storing a WB token must start the harvest it unlocks.

A seller who pastes a token has an empty workspace, and nothing used to connect
the two events: the credential was stored, and the SKUs it unlocks appeared at
06:00 MSK the next morning. No error was raised in between, so the only signal
was a product page with no products on it.

What is pinned here is the TRIGGER CONDITION, because that is the part with a
decision in it. A surface becoming reachable is the event worth a harvest; the
same token pasted twice is not, and must not spend WB's shared rate budget.
The tier's in-memory Redis backs the debounce, so the claim under test is the
real one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet

from src.modules.users.deps import get_user_repo
from src.modules.workspaces.deps import get_workspace_repo, get_workspace_token_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import (
    FakeUserRepository,
    FakeWorkspaceRepository,
    FakeWorkspaceTokenRepository,
)

TOKEN = "eyJhbGciOiJFUzI1NiJ9.a-real-looking-wb-token"


@pytest.fixture(autouse=True)
def _wire_workspace_repositories(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    workspace_token_repo: FakeWorkspaceTokenRepository,
    settings_override: Any,
) -> Any:
    """Serve the workspace routes from in-memory repositories with a real key."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_workspace_token_repo, workspace_token_repo)
    with settings_override(fernet_secret_key=Fernet.generate_key().decode()):
        yield


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture what the route asks Celery to run, without a broker.

    Patched at ``send_task`` rather than at ``enqueue_catalogue_bootstrap`` so
    the debounce, the task name and the argument shape are all still the real
    ones — replacing the whole helper would leave nothing under test but an
    ``if``.
    """
    calls: list[dict[str, Any]] = []

    def _send_task(name: str, kwargs: dict[str, Any] | None = None, **_: Any) -> Any:
        calls.append({"name": name, "kwargs": kwargs or {}})
        return type("Task", (), {"id": f"task-{len(calls)}"})()

    monkeypatch.setattr("src.modules.workspaces.bootstrap.celery_app.send_task", _send_task)
    return calls


async def test_a_first_token_enqueues_both_the_monitoring_and_finance_walks(
    client: httpx.AsyncClient,
    dev_user: Any,
    workspace: Workspace,
    enqueued: list[dict[str, Any]],
) -> None:
    """The event this feature exists for: WB is connected, so go and look.

    Both walks, not just the catalogue one. A seller who has connected WB
    expects their P&L to fill in too, and finance reads a different WB surface
    from monitoring, so there is nothing to gain by making one wait.

    Each task must be addressed to the workspace whose token was stored — a
    harvest pointed anywhere else would read another seller's account with
    these credentials.
    """
    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/tokens",
        headers=auth_headers(dev_user.id),
        json={"tokens": {"unified": TOKEN}},
    )

    assert response.status_code == 200
    assert [call["name"] for call in enqueued] == [
        "monitoring.discover_workspace",
        "finreports.harvest_finance",
    ]
    assert all(call["kwargs"] == {"workspace_id": str(workspace.id)} for call in enqueued)


async def test_re_saving_the_same_surface_does_not_enqueue_a_second_harvest(
    client: httpx.AsyncClient,
    dev_user: Any,
    workspace: Workspace,
    enqueued: list[dict[str, Any]],
) -> None:
    """Rotation is not discovery.

    Re-pasting a token for a surface that already had one reveals no SKU the
    catalogue could not already see. Enqueueing there would let a settings page
    spend the WB rate budget every time it was saved.
    """
    url = f"/api/v1/workspaces/{workspace.id}/tokens"
    headers = auth_headers(dev_user.id)

    first = await client.put(url, headers=headers, json={"tokens": {"unified": TOKEN}})
    second = await client.put(url, headers=headers, json={"tokens": {"unified": "a-new-token"}})

    assert first.status_code == 200
    assert second.status_code == 200
    # The first save's pair, and nothing from the second.
    assert len(enqueued) == 2


async def test_a_broker_that_refuses_still_stores_the_token(
    client: httpx.AsyncClient,
    dev_user: Any,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The token is the request; the harvest is a courtesy attached to it.

    A broker that has gone away must cost the seller a slower first harvest —
    the nightly pass is still the backstop — not a failed save and the belief
    that their credentials did not stick.
    """

    def _explode(*_: Any, **__: Any) -> Any:
        raise RuntimeError("broker is gone")

    monkeypatch.setattr("src.modules.workspaces.bootstrap.celery_app.send_task", _explode)

    response = await client.put(
        f"/api/v1/workspaces/{workspace.id}/tokens",
        headers=auth_headers(dev_user.id),
        json={"tokens": {"unified": TOKEN}},
    )

    assert response.status_code == 200
    assert response.json()["configured"] == ["unified"]


async def test_an_unknown_workspace_never_reaches_the_queue(
    client: httpx.AsyncClient,
    dev_user: Any,
    enqueued: list[dict[str, Any]],
) -> None:
    """Tenancy is decided before the enqueue, not after.

    ``enqueue_catalogue_bootstrap`` performs no tenancy check of its own, so the
    404 from the service layer is the only thing standing between a stranger's
    workspace id and a harvest run against it.
    """
    response = await client.put(
        f"/api/v1/workspaces/{uuid.uuid4()}/tokens",
        headers=auth_headers(dev_user.id),
        json={"tokens": {"unified": TOKEN}},
    )

    assert response.status_code == 404
    assert enqueued == []
