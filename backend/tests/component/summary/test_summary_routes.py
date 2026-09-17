"""Component tests for the «Сводка» HTTP surface.

The arithmetic is covered in ``tests/unit/summary``; what is proved here is the
transport contract — who may reach the route at all, that the caller's active
workspace scopes the read, and that the window is bounded before it reaches a
query rather than after.

The window bound carries real weight. This route aggregates settlement detail,
and the largest workspace on this service carries ~670 000 rows: an unbounded
window is one authenticated caller making Postgres do a minute of work per
keystroke, which is a denial of service with a valid token attached.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from src.core.timeutils import moscow_today
from src.modules.summary.deps import get_summary_service
from src.modules.summary.routers.summary import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS
from src.modules.summary.schemas import SummaryCoverage, SummaryKpi, SummaryResponse
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository


class _StubSummaryService:
    """Records the window, workspace and options each request resolves."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[dict[str, Any]] = []

    async def build(self, _session: Any, **kwargs: Any) -> SummaryResponse:
        """Echo the resolved request back through an empty summary."""
        self.calls.append(kwargs)
        return SummaryResponse(
            date_from=kwargs["date_from"],
            date_to=kwargs["date_to"],
            currency="KGS",
            kpi=SummaryKpi(
                revenue_paid=Decimal("19446433"),
                revenue_seller=Decimal("23000000"),
                margin=None,
                sold_units=6185,
                orders=20819,
                buyouts=5665,
                uncosted_skus=2,
                penalties=Decimal("12000"),
                ad_spend=Decimal("300000"),
            ),
            days=[],
            rows=[],
            coverage=SummaryCoverage(
                settlement_from=None,
                settlement_to=None,
                funnel_from=None,
                funnel_to=None,
                advertising_from=None,
                advertising_to=None,
            ),
        )


@pytest.fixture
def summary() -> _StubSummaryService:
    """The stub service the route is wired to."""
    return _StubSummaryService()


@pytest.fixture(autouse=True)
def _wire_summary(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    summary: _StubSummaryService,
) -> None:
    """Wire identity, tenancy and the stubbed summary service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_summary_service, summary)


@pytest.fixture(autouse=True)
def _internal_caller(login_as: Callable[..., None]) -> None:
    """The surface is internal-only, so every test is one of us by default."""
    login_as(is_primary_org=True)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}


async def test_a_customer_cannot_reach_the_summary(
    client: httpx.AsyncClient, headers: dict[str, str], login_as: Callable[..., None]
) -> None:
    """An ordinary tenant gets 403, not a restated margin.

    «Сводка» swaps WB's weekly advertising invoice for the burn the statistics
    recorded and withholds the margin entirely until every SKU is costed.
    Neither choice has been explained to a customer, and a figure a seller
    cannot reconcile against WB's own cabinet is worse than no figure.
    """
    login_as(is_primary_org=False)

    response = await client.get("/api/v1/summary", headers=headers)

    assert response.status_code == 403


async def test_the_summary_is_scoped_to_the_active_workspace(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    summary: _StubSummaryService,
    workspace: Workspace,
) -> None:
    """The workspace from the header, not the token, scopes the read.

    One seller's revenue must never be resolvable from another's session just
    because both belong to the same user.
    """
    response = await client.get("/api/v1/summary", headers=headers)

    assert response.status_code == 200
    assert summary.calls[0]["workspace_id"] == workspace.id


async def test_without_a_workspace_header_nothing_resolves(
    client: httpx.AsyncClient, user: Any, summary: _StubSummaryService
) -> None:
    """No active workspace means no answer, not a default one."""
    response = await client.get("/api/v1/summary", headers=auth_headers(user.id))

    assert response.status_code >= 400
    assert summary.calls == []


async def test_an_omitted_window_defaults_to_the_last_week(
    client: httpx.AsyncClient, headers: dict[str, str], summary: _StubSummaryService
) -> None:
    """No dates means a week ending on the MOSCOW day.

    WB dates every settlement row by the Moscow calendar, so resolving the open
    end from the host's own clock drops the newest day for the three hours
    between 00:00 and 03:00 MSK. The length is the page's own: «Сводка» answers
    «как идут дела сейчас», and a month of history flattens the few days that
    answer it.
    """
    await client.get("/api/v1/summary", headers=headers)

    call = summary.calls[0]
    assert call["date_to"] == moscow_today()
    assert call["date_from"] == moscow_today() - timedelta(days=DEFAULT_WINDOW_DAYS)


async def test_a_window_longer_than_the_cap_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], summary: _StubSummaryService
) -> None:
    """A multi-year window is rejected before it reaches a query.

    The check has to happen here, not in the service: the point is that no
    aggregation runs at all.
    """
    end = date(2026, 9, 6)
    start = end - timedelta(days=MAX_WINDOW_DAYS + 1)

    response = await client.get(
        "/api/v1/summary",
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
        headers=headers,
    )

    assert response.status_code == 422
    assert summary.calls == []


async def test_an_inverted_window_is_refused(
    client: httpx.AsyncClient, headers: dict[str, str], summary: _StubSummaryService
) -> None:
    """A start after its end is a 422, not an empty summary."""
    response = await client.get(
        "/api/v1/summary",
        params={"date_from": "2026-09-06", "date_to": "2026-07-15"},
        headers=headers,
    )

    assert response.status_code == 422
    assert summary.calls == []


async def test_the_rejection_does_not_echo_the_dates_back(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    """A validation message names the rule, never the submitted value.

    FastAPI's own 422 handler returns the offending input; this route raises a
    domain error instead precisely so nothing a caller sent comes back out.
    """
    response = await client.get(
        "/api/v1/summary",
        params={"date_from": "2026-09-06", "date_to": "2026-07-15"},
        headers=headers,
    )

    assert "2026-09-06" not in response.text


async def test_the_window_is_the_only_thing_the_route_takes(
    client: httpx.AsyncClient, headers: dict[str, str], summary: _StubSummaryService
) -> None:
    """Price base and grouping are not parameters, and an old link is harmless.

    Both used to be query parameters, and every click on one cost a round trip
    over the whole settlement window — seconds, for arithmetic the page can do
    on data it already holds. A stale bookmark carrying them must still answer
    rather than 422: they are simply not read.
    """
    response = await client.get(
        "/api/v1/summary",
        params={"revenue_base": "seller", "grouping": "brand"},
        headers=headers,
    )

    assert response.status_code == 200
    assert set(summary.calls[0]) == {"workspace_id", "date_from", "date_to"}
