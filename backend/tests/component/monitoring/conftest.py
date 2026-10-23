"""Shared scaffolding for the monitoring component tests.

The analytics service is stubbed on purpose: its arithmetic already has deep
unit coverage (``tests/unit/monitoring``), and repeating it through HTTP would
be slow and duplicated. What this tier adds is everything *around* the service.

The stubs and their wiring live here rather than in one of the test modules
because two of them now need the same fixtures — the routes' own behaviour and
the subscription ramp that gates writing to them are separate subjects with one
set-up.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from src.core.exceptions import NotFoundError, ValidationError
from src.modules.monitoring.deps import get_analytics_service, get_product_card_repo
from src.modules.monitoring.schemas import (
    MetricWindow,
    PinnedSkusResponse,
    SkuLookupResponse,
    SkuSummaryListResponse,
)
from src.modules.users.deps import get_user_repo
from src.modules.workspaces.contract import WORKSPACE_HEADER
from src.modules.workspaces.deps import get_workspace_repo
from src.modules.workspaces.models import Workspace
from tests.support.auth import auth_headers
from tests.support.fakes import FakeUserRepository, FakeWorkspaceRepository

NM_ID = 953770957
FOREIGN_NM_ID = 999999999


class _StubAnalyticsService:
    """Answers exactly the calls these routes make, recording the arguments."""

    def __init__(self) -> None:
        """Start with no recorded calls and benign default answers."""
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: SKUs the bulk "Refresh all SKUs" refresh will enqueue over.
        self.workspace_nm_ids: list[int] = [NM_ID]

    async def list_workspace_nm_ids(self, **kwargs: Any) -> list[int]:
        """Return the workspace's SKU list, recording the call."""
        self.calls.append(("list_workspace_nm_ids", kwargs))
        return self.workspace_nm_ids

    async def get_summary(self, **kwargs: Any) -> SkuSummaryListResponse:
        """Return an empty listing, recording the resolved window and paging."""
        self.calls.append(("get_summary", kwargs))
        return SkuSummaryListResponse(
            window=MetricWindow(start=date(2026, 7, 1), end=date(2026, 7, 7)),
            count=0,
            total=0,
            limit=kwargs.get("limit", 100),
            offset=kwargs.get("offset", 0),
            items=[],
        )

    async def list_pinned_skus(self, **kwargs: Any) -> PinnedSkusResponse:
        """Return an empty chip row."""
        self.calls.append(("list_pinned_skus", kwargs))
        return PinnedSkusResponse(items=[])

    async def lookup_skus_by_vendor_code(
        self, vendor_code: str, **kwargs: Any
    ) -> SkuLookupResponse:
        """Return no matches, recording the searched vendor code."""
        self.calls.append(("lookup", {"vendor_code": vendor_code, **kwargs}))
        return SkuLookupResponse(query=vendor_code, count=0, items=[])

    async def get_detail(self, **kwargs: Any) -> Any:
        """Report the SKU as having no data in the window."""
        self.calls.append(("get_detail", kwargs))
        raise NotFoundError(f"No monitoring data for SKU {kwargs.get('nm_id')}.")

    async def reorder_pins(self, **kwargs: Any) -> PinnedSkusResponse:
        """Reject the reorder the way the real service does on a stale list."""
        self.calls.append(("reorder_pins", kwargs))
        raise ValidationError("The list is not exactly the current pinned set.")


class _StubProductCardRepo:
    """SKU → workspace registry answering the ownership guard."""

    def __init__(self, owned: set[int]) -> None:
        """Record which SKUs the active workspace owns."""
        self.owned = owned

    async def is_in_workspace(self, *, nm_id: int, workspace_id: Any) -> bool:
        """Report whether this SKU belongs to the caller's workspace."""
        return nm_id in self.owned


@pytest.fixture
def analytics() -> _StubAnalyticsService:
    """The stub service the routes are wired to."""
    return _StubAnalyticsService()


@pytest.fixture(autouse=True)
def _wire_monitoring(
    override: Callable[[Any, Any], None],
    user_repo: FakeUserRepository,
    workspace_repo: FakeWorkspaceRepository,
    analytics: _StubAnalyticsService,
) -> None:
    """Wire identity, tenancy, the SKU registry, and the stubbed service."""
    override(get_user_repo, user_repo)
    override(get_workspace_repo, workspace_repo)
    override(get_product_card_repo, _StubProductCardRepo({NM_ID}))
    override(get_analytics_service, analytics)


@pytest.fixture
def headers(user: Any, workspace: Workspace) -> dict[str, str]:
    """Authenticated headers carrying the active workspace."""
    return {**auth_headers(user.id), WORKSPACE_HEADER: str(workspace.id)}
