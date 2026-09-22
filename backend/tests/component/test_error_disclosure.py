"""A failure of ours must not answer the caller with our internals.

Register P0.3. Every ``AppError`` had its ``message`` serialised straight into
the response body, and on the 5xx path those messages are written for whoever
debugs them: a pydantic report naming our WB schema fields, the WB host and path
we called, the fact that one code path shells out to ``curl``. The SPA renders
``error.message`` verbatim, so a seller whose harvest failed was shown that text.

Worse, it travelled in exactly the wrong direction — the handler logged the code
and the status but never the message, so the operator got less than the
attacker did.

The rule is enforced in the handler rather than at each ``raise``: a 5xx answers
with the error class's ``client_message``, whatever the raise site wrote. That
makes it a property of the transport, not a discipline every future call site has
to remember.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from src.core.exceptions import AppError, IntegrationError, ValidationError
from src.modules.monitoring.deps import get_analytics_service
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

#: Stand-in for the upstream text these messages actually carry.
LEAKED_DETAIL = "card detail row failed validation: 3 validation errors for WBCardRow"


class _FailingAnalytics:
    """Fails the way the WB clients do, with a message written for a developer."""

    async def get_summary(self, **kwargs: Any) -> Any:
        """Raise an upstream failure carrying internal detail."""
        raise IntegrationError(LEAKED_DETAIL)


@pytest.fixture(autouse=True)
def _wire(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
) -> None:
    """Wire identity, tenancy and the failing analytics service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_analytics_service, _FailingAnalytics())


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_an_upstream_failure_does_not_return_its_own_detail(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """The 502 body carries none of the text the raise site wrote.

    Asserted against the WHOLE body rather than the message field: the point is
    that the detail does not reach the client at all, by any route through the
    envelope.
    """
    response = await client.get("/api/v1/monitoring/summary", headers=headers)

    assert response.status_code == 502
    assert LEAKED_DETAIL not in response.text
    assert "validation errors" not in response.text


async def test_the_caller_still_learns_what_kind_of_failure_it_was(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """Withholding detail must not leave the SPA with nothing to show.

    The machine-readable code is unchanged and the message is a real sentence,
    because the frontend renders ``error.message`` directly — an empty one would
    surface to a seller as a blank error.
    """
    response = await client.get("/api/v1/monitoring/summary", headers=headers)

    body = response.json()["error"]
    assert body["code"] == "integration_error"
    assert body["message"] == IntegrationError.client_message
    assert body["message"].strip()


async def test_a_client_error_still_speaks_for_itself(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A 4xx message is written for the person who caused it and must survive.

    This is the half the fix must not break: "Воркспейс «X» уже существует" is
    the answer, not an internal detail, and blanket-replacing every message
    would have turned every actionable error into "что-то пошло не так".
    """
    response = await client.put(
        "/api/v1/monitoring/pins/order",
        headers=headers,
        json={"nm_ids": [1, 1]},
    )

    assert response.status_code == 422
    assert "nm_ids" in response.text


def test_the_rule_is_keyed_on_the_status_not_the_class() -> None:
    """Any 5xx withholds; any 4xx does not — including classes added later.

    A per-class allowlist would leak the first time someone introduced a new
    server-side error and did not think about this file.
    """

    class NewUpstreamError(AppError):
        """A 5xx nobody has written a disclosure rule for."""

        http_status = 503

    leaked = NewUpstreamError("internal detail nobody vetted")
    client_error = ValidationError("Дата начала позже даты конца.")

    assert leaked.public_message != "internal detail nobody vetted"
    assert client_error.public_message == "Дата начала позже даты конца."
