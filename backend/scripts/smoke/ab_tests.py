"""«A/Б-тесты»: the list of tests and the newest test's page.

What ``AbTestsView`` asks for when it opens — ``GET /ab-tests`` with no search —
and what ``AbTestDetailView`` asks for: ``GET /ab-tests/{id}``, here for the
newest test, which is the first row of the list. The service is built by
``ab_tests/deps``' own provider.

Not opened: the photos (``GET /ab-tests/{id}/variants/{id}/image``). They are
files in object storage rather than rows, and fetching them is the one part of
these pages that leaves Postgres.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.smoke.report import PageSkipped, SmokeReport, attempt
from src.core.config import settings
from src.modules.ab_tests.deps import get_catalog_service
from src.modules.ab_tests.repos import (
    AbTestRepository,
    CampaignRepository,
    ExposureRepository,
    SnapshotRepository,
    VariantRepository,
    WindowRepository,
)
from src.modules.ab_tests.services.storage import build_media_store


async def check_ab_tests(
    session: AsyncSession, report: SmokeReport, *, workspace_id: uuid.UUID
) -> None:
    """Open the A/Б list, then the newest test on it."""
    service = get_catalog_service(
        tests=AbTestRepository(session),
        variants=VariantRepository(session),
        exposures=ExposureRepository(session),
        stats=WindowRepository(session),
        snapshots=SnapshotRepository(session),
        campaigns=CampaignRepository(session),
        # Not the api's shared store (`get_media_store`), which keeps a
        # connection open for the life of the process: neither page touches a
        # photo, and this one opens nothing that would outlive the probe's loop.
        media_store=build_media_store(settings),
    )
    newest: uuid.UUID | None = None

    async def listing() -> int:
        nonlocal newest
        tests = await service.list_tests(workspace_id=workspace_id, query=None)
        for test in tests:
            test.model_dump_json()
        newest = tests[0].id if tests else None
        return len(tests)

    async def detail() -> int:
        if newest is None:
            raise PageSkipped("no test to open" if listed else "the list it is opened from broke")
        answer = await service.get_detail(workspace_id=workspace_id, test_id=newest)
        answer.model_dump_json()
        return len(answer.variants)

    listed = await attempt(session, report, "A/Б list", listing)
    await attempt(session, report, "A/Б test", detail)


__all__ = ["check_ab_tests"]
