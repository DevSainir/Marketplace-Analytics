"""Celery entrypoint for the daily photo rotation.

Runs after the monitoring harvest, because it reads the advertising rows that
harvest writes. It makes no WB *read* calls of its own for exactly that reason —
``fullstats`` allows roughly one request a minute per seller, and a second
caller on the same token pushes the bucket over, which WB answers with a 500 or
a hung socket rather than a clean 429.

It does make one WB *write* per rotating test: the media upload that puts the
next photo on the card.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from src.core.celery_app import celery_app
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.core.tasks import run_task
from src.core.timeutils import moscow_today
from src.integrations.wildberries import WBContentClient
from src.modules.ab_tests.deps import get_media_store
from src.modules.ab_tests.repos import (
    AbTestRepository,
    ExposureRepository,
    VariantStatRepository,
)
from src.modules.ab_tests.services.photos import VariantInstaller
from src.modules.ab_tests.services.runner import RotationRunner
from src.modules.monitoring.contract import AdDay, load_ad_days_for_nm
from src.modules.workspaces.contract import load_workspace_token_bundle

logger = get_logger(__name__)


async def _advance_all() -> dict[str, int]:
    """Advance every running test by one pass.

    One session and one transaction per test, so a WB failure on one test
    cannot roll back the days already attributed to another.

    Returns:
        ``{"tests": n, "rotated": n, "completed": n, "failed": n}``.
    """
    # Yesterday: WB serves no advertising for the current day, and a partial
    # day would under-count the live photo and delay its rotation.
    through = moscow_today() - timedelta(days=1)

    async with AsyncSessionLocal() as session:
        tests = await AbTestRepository(session).list_advanceable()

    counters = {"tests": len(tests), "rotated": 0, "completed": 0, "failed": 0}

    for test in tests:
        try:
            async with AsyncSessionLocal() as session:
                repo = AbTestRepository(session)
                loaded = await repo.get(workspace_id=test.workspace_id, test_id=test.id)
                if loaded is None:  # deleted between the listing and now
                    continue

                bundle = await load_workspace_token_bundle(session, workspace_id=test.workspace_id)
                token = (bundle.content or bundle.analytics) if bundle else ""
                if not token:
                    logger.warning(
                        "ab_tests: workspace %s has no content token; skipping test %s",
                        test.workspace_id,
                        test.id,
                    )
                    continue

                # `workspace` is bound as a DEFAULT, not captured: this closure
                # is defined inside the per-test loop, and a free reference to
                # `test` would resolve to whatever the loop variable holds when
                # the closure finally runs. It happens to run in the same
                # iteration today, so the bug would not bite until someone
                # deferred the call — at which point every test's advertising
                # would be scoped to the LAST workspace in the batch.
                async def _load_days(
                    nm_id: int,
                    date_from: date,
                    date_to: date,
                    workspace: uuid.UUID = test.workspace_id,
                ) -> Sequence[AdDay]:
                    return await load_ad_days_for_nm(
                        session,
                        workspace_id=workspace,
                        nm_id=nm_id,
                        date_from=date_from,
                        date_to=date_to,
                    )

                async with WBContentClient(settings, token=token) as client:
                    runner = RotationRunner(
                        tests=repo,
                        exposures=ExposureRepository(session),
                        stats=VariantStatRepository(session),
                        installer=VariantInstaller(
                            content_client=client, media_store=get_media_store()
                        ),
                        load_ad_days=_load_days,
                    )
                    outcome = await runner.advance(loaded, through=through)

                await session.commit()

            if outcome.installed_variant_id is not None:
                counters["rotated"] += 1
            if outcome.action.value == "complete":
                counters["completed"] += 1
        except IntegrationError as exc:
            counters["failed"] += 1
            logger.warning("ab_tests: test %s could not advance: %s", test.id, exc)

    logger.info("ab_tests: rotation pass %s", counters)
    return counters


@celery_app.task(  # type: ignore[untyped-decorator]
    name="ab_tests.advance_rotations",
    bind=False,
)
def advance_rotations() -> dict[str, int]:
    """Scheduled entrypoint: attribute yesterday and rotate the tests that are due.

    Returns:
        Per-pass counters, as :func:`_advance_all` returns them.
    """
    return run_task(_advance_all())


__all__ = ["advance_rotations"]
