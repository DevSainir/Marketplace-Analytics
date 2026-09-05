"""Creating a test must produce a row without touching an unloaded collection.

This is the gap that let a 500 reach CI on 2026-09-05. The list row is built by
one projection shared by every caller, and that projection reads
``len(test.variants)``. On a test the repository has just inserted, the
relationship has never been loaded — so reading it emits a lazy SELECT, and a
lazy SELECT on an async session raises ``MissingGreenlet`` rather than returning
an empty list.

Nothing below the browser tier could see it: the component tier stubs the
service, and the repository tests never build a row. So the check lives here,
against a real session, where a lazy load is a real lazy load.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ValidationError
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.schemas import AbTestCreate
from src.modules.ab_tests.services.catalog import AbTestCatalogService
from src.modules.ab_tests.services.storage import LocalMediaStore
from src.modules.monitoring.contract import WorkspaceCard
from src.modules.organizations.models import Organization
from src.modules.workspaces.models import Workspace

NM_FLOWER_DRESS = 995716075

#: The catalogue card the article resolves to. Creating a test needs one.
_CARD = WorkspaceCard(
    nm_id=NM_FLOWER_DRESS, vendor_code="ДЕТ_ПЛАТЬЕ_ЦВЕТОЧЕК", title="Платье в цветочек"
)


def _service(session: AsyncSession, tmp_path: Path) -> AbTestCatalogService:
    """The real service over real repositories."""
    return AbTestCatalogService(
        tests=AbTestRepository(session),
        variants=VariantRepository(session),
        exposures=ExposureRepository(session),
        stats=WindowRepository(session),
        media_store=LocalMediaStore(tmp_path),
    )


@pytest.mark.integration
async def test_creating_a_test_returns_a_row_with_no_variants(
    db_session: AsyncSession, organization: Organization, tmp_path: Path
) -> None:
    """A fresh test reports zero photos instead of raising on a lazy load.

    The assertion that matters is that this returns at all: before the fix the
    projection raised ``MissingGreenlet`` and the route answered 500, which the
    SPA showed as a creation that silently did nothing.
    """
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization.id, name="Демо")
    db_session.add(workspace)
    await db_session.flush()

    row = await _service(db_session, tmp_path).create_test(
        workspace_id=workspace.id,
        payload=AbTestCreate(nm_id=NM_FLOWER_DRESS, name="Тест главного фото"),
        card=_CARD,
    )

    assert row.variant_count == 0
    assert row.active_variant_id is None
    assert row.trigger_mode == "impressions"
    assert row.status == "draft"


@pytest.mark.integration
async def test_the_new_test_is_listed_immediately_after_creation(
    db_session: AsyncSession, organization: Organization, tmp_path: Path
) -> None:
    """The same projection runs over a loaded query, and both agree.

    Creating and listing build the row through one helper; if only the listing
    path were exercised the create path could keep raising unnoticed.
    """
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization.id, name="Демо")
    db_session.add(workspace)
    await db_session.flush()
    service = _service(db_session, tmp_path)

    created = await service.create_test(
        workspace_id=workspace.id,
        payload=AbTestCreate(nm_id=NM_FLOWER_DRESS, name="Тест главного фото"),
        card=_CARD,
    )
    listed = await service.list_tests(workspace_id=workspace.id, query=None)

    assert [row.id for row in listed] == [created.id]
    assert listed[0].variant_count == created.variant_count


@pytest.mark.integration
async def test_an_article_outside_the_catalogue_cannot_start_a_test(
    db_session: AsyncSession, organization: Organization, tmp_path: Path
) -> None:
    """An unresolved article is refused, and nothing is written.

    `nm_id=1` was accepted until 2026-09-05. Nothing downstream would have
    worked: the poller reads advertising for that article and finds none, and a
    rotation would send a media upload at somebody else's card, or at nothing.
    The refusal has to happen before the row exists, because a test that cannot
    rotate is worse than no test — it looks like it is running.
    """
    workspace = Workspace(id=uuid.uuid4(), organization_id=organization.id, name="Демо")
    db_session.add(workspace)
    await db_session.flush()
    service = _service(db_session, tmp_path)

    with pytest.raises(ValidationError, match="1"):
        await service.create_test(
            workspace_id=workspace.id,
            payload=AbTestCreate(nm_id=1, name="Тест"),
            card=None,
        )

    assert await service.list_tests(workspace_id=workspace.id, query=None) == []
