"""The request log, exercised through the real middleware (register P2.2).

The unit tier proves the formatter is safe and carries whatever is bound. What
it cannot prove is that anything actually binds — that the middleware runs, that
the auth dependency attributes the line to an account, and that the id a
customer can quote comes back on the response.

The last one is the whole practical value of a request id. "It failed around
two" is not a search; ``X-Request-Id: 6f1c2ab90d34`` is.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.core import logcontext
from tests.component.conftest import CapturingHandler
from tests.support.auth import auth_headers

pytestmark = pytest.mark.component


@pytest.fixture(autouse=True)
def _clean_context() -> Any:
    """No context may leak between these tests."""
    logcontext.reset_context()
    yield
    logcontext.reset_context()


async def test_the_response_carries_an_id_a_customer_can_quote(
    client: httpx.AsyncClient,
) -> None:
    """The one string that turns "it failed around two" into a search."""
    # Act
    response = await client.get("/api/v1/organizations/me")

    # Assert
    request_id = response.headers.get("X-Request-Id")
    assert request_id, "every served request must come back with its id"
    assert len(request_id) == 12


async def test_two_requests_get_different_ids(client: httpx.AsyncClient) -> None:
    """An id shared by every request correlates nothing."""
    # Act
    first = await client.get("/api/v1/organizations/me")
    second = await client.get("/api/v1/organizations/me")

    # Assert
    assert first.headers["X-Request-Id"] != second.headers["X-Request-Id"]


async def test_the_request_line_carries_its_context_and_outcome(
    client: httpx.AsyncClient, captured_log: CapturingHandler
) -> None:
    """What an alert rule binds to: status as a field, not as prose."""
    # Act
    response = await client.get("/api/v1/organizations/me")

    # Assert
    served = [p for p in captured_log.payloads() if p["message"] == "request served"]
    assert len(served) == 1, "exactly one line per request"
    line = served[0]
    assert line["status"] == response.status_code
    assert line["method"] == "GET"
    assert line["path"] == "/api/v1/organizations/me"
    assert line["request_id"] == response.headers["X-Request-Id"]
    assert isinstance(line["duration_ms"], float)


async def test_an_authenticated_line_names_the_account(
    client: httpx.AsyncClient,
    captured_log: CapturingHandler,
    user: Any,
    authenticated: None,
) -> None:
    """The difference between a fact and an answer, end to end.

    A real signed token, resolved by the real dependency — the binding happens
    in ``get_current_user_id``, so stubbing the guard would test nothing.
    """
    # Act
    await client.get("/api/v1/workspaces", headers=auth_headers(user.id))

    # Assert
    served = [p for p in captured_log.payloads() if p["message"] == "request served"]
    assert served[0]["user_id"] == str(user.id)


async def test_the_liveness_probe_is_not_logged(
    client: httpx.AsyncClient, captured_log: CapturingHandler
) -> None:
    """Orchestrator polling every few seconds would bury everything else."""
    # Act
    await client.get("/health")

    # Assert
    assert captured_log.payloads() == []


async def test_context_does_not_survive_the_request(client: httpx.AsyncClient) -> None:
    """A value left bound would attribute the NEXT caller's lines to this one."""
    # Act
    await client.get("/api/v1/organizations/me")

    # Assert
    assert logcontext.current_context() == {}
