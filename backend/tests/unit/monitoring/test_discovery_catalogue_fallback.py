"""A refused catalogue must not void the workspace's other WB sources.

Discovery names the SKUs; it does not produce any of the facts a harvest
persists. Treating its failure as fatal meant one revoked scope silenced every
other source — funnel, advertising, stocks, prices — for a workspace whose SKU
list had not changed at all.

On 2026-08-21 WB stopped serving ``/content/v2/get/cards/list`` on the
analytics scope, so a workspace harvested nothing at 06:00 MSK while its
catalogue sat unchanged in Postgres.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest

from src.core.exceptions import IntegrationError
from src.modules.monitoring.tasks import discovery
from src.modules.monitoring.tasks.harvest import HarvestOutcome
from src.modules.workspaces.contract import WorkspaceTokenBundle

WORKSPACE = WorkspaceTokenBundle(
    workspace_id="019f657a-a70c-780a-ac98-f010a1916615",  # type: ignore[arg-type]
    name="Демо",
    content="content-token",
    analytics="analytics-token",
    advertising="advertising-token",
)
CATALOGUE = [953770957, 995716075]


class _RefusingContentClient:
    """A Content API client that answers every catalogue read with a 403."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Accept the production constructor signature and ignore it."""

    async def __aenter__(self) -> _RefusingContentClient:
        """Enter the client's async context."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Leave the client's async context."""

    async def fetch_all_cards(self) -> list[object]:
        """Refuse, exactly as WB does for a token without «Контент»."""
        raise IntegrationError("WildBerries API error 403 on /content/v2/get/cards/list.")


class _FakeProductCardRepository:
    """A catalogue holding whatever SKUs the test registered."""

    def __init__(self, session: object, *, nm_ids: list[int]) -> None:
        """Bind the fake to the SKUs it should report."""
        self._nm_ids = nm_ids

    async def list_workspace_nm_ids(self, workspace_id: object) -> list[int]:
        """Return the workspace's registered SKUs."""
        return list(self._nm_ids)


@pytest.fixture
def harvested(monkeypatch: pytest.MonkeyPatch, settings_override: Any) -> Iterator[dict[str, Any]]:
    """Stub the WB catalogue read and capture what the harvest was asked for.

    ``wb_fake_harvest`` is pinned off because these tests are about the REAL
    discovery path; the fake one never calls the Content API at all, and
    leaving the flag to the ambient settings makes the result depend on which
    tests ran first.
    """
    captured: dict[str, Any] = {}

    async def _fake_harvest(**kwargs: Any) -> HarvestOutcome:
        captured.update(kwargs)
        return HarvestOutcome(counts={"funnel_rows": 287, "advertising_rows": 24})

    monkeypatch.setattr(discovery, "WBContentClient", _RefusingContentClient)
    monkeypatch.setattr(discovery, "refresh_workspace_data", _fake_harvest)
    monkeypatch.setattr(discovery, "moscow_today", lambda: date(2026, 8, 21))

    @asynccontextmanager
    async def _session() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(discovery, "AsyncSessionLocal", _session)
    with settings_override(wb_fake_harvest=False):
        yield captured


async def test_a_refused_catalogue_falls_back_to_the_skus_on_file(
    monkeypatch: pytest.MonkeyPatch, harvested: dict[str, Any]
) -> None:
    """A 403 on the Content API still harvests the workspace's known SKUs.

    Yesterday's SKU list is a sound basis for yesterday's facts — the catalogue
    is the most static source a harvest touches.
    """
    monkeypatch.setattr(
        discovery,
        "ProductCardRepository",
        lambda session: _FakeProductCardRepository(session, nm_ids=CATALOGUE),
    )

    counts = await discovery._discover_and_harvest_workspace(WORKSPACE, days=7)

    assert counts == {"funnel_rows": 287, "advertising_rows": 24}
    assert harvested["nm_ids"] == CATALOGUE
    assert harvested["cards"] is None


async def test_a_refused_catalogue_with_no_skus_on_file_still_fails(
    monkeypatch: pytest.MonkeyPatch, harvested: dict[str, Any]
) -> None:
    """With no catalogue and no Content API there is genuinely nothing to do.

    The workspace must be reported failed rather than recording a zero-row
    success, which is what the nightly run's failure count exists to surface.
    """
    monkeypatch.setattr(
        discovery,
        "ProductCardRepository",
        lambda session: _FakeProductCardRepository(session, nm_ids=[]),
    )

    with pytest.raises(IntegrationError, match="no SKUs on file"):
        await discovery._discover_and_harvest_workspace(WORKSPACE, days=7)

    assert harvested == {}


async def test_a_workspace_without_a_content_token_harvests_its_known_skus(
    monkeypatch: pytest.MonkeyPatch, harvested: dict[str, Any]
) -> None:
    """A missing token is the same event as a refused one, and as recoverable.

    Adding a WB surface the deployment has no token for yet must not stop the
    surfaces it does have from being harvested.
    """
    monkeypatch.setattr(
        discovery,
        "ProductCardRepository",
        lambda session: _FakeProductCardRepository(session, nm_ids=CATALOGUE),
    )
    tokenless = WORKSPACE.model_copy(update={"content": ""})

    counts = await discovery._discover_and_harvest_workspace(tokenless, days=7)

    assert counts == {"funnel_rows": 287, "advertising_rows": 24}
    assert harvested["nm_ids"] == CATALOGUE
