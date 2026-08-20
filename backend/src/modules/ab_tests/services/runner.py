"""The daily rotation pass: attribute yesterday, then swap the photo if due.

Runs without a request, once a day, after the monitoring harvest has written the
advertising rows this reads. The order inside one test matters and is the whole
design:

1. **Attribute first.** Yesterday's impressions belong to the photo that was up
   yesterday, so they must be recorded before anything changes.
2. **Then decide**, on the live photo's accumulated total.
3. **Install, and only then record.** The exposure row and the active-variant
   pointer are written after WB accepts the upload, never before. A pointer that
   moves on a failed upload would credit every following day to a picture that
   is not on the card.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from src.core.logging import get_logger
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.attribution import (
    AttributedDay,
    DailyCounts,
    ExposureWindow,
    attribute_days,
)
from src.modules.ab_tests.services.rotation import RotationAction, RotationState, decide

logger = get_logger(__name__)

#: How far back a pass re-reads advertising. WB restates recent days as
#: conversions settle, so days already stored are refreshed rather than trusted.
LOOKBACK_DAYS: int = 30

#: Signature of the monitoring contract's ad-day loader, narrowed to what this
#: module needs so the runner can be tested without a session.
AdDayLoader = Callable[[int, date, date], Awaitable[Sequence[DailyCounts]]]


class _Exposures(Protocol):
    """The exposure repository, as the runner uses it."""

    async def windows_for_test(self, *, test_id: uuid.UUID) -> list[ExposureWindow]: ...

    async def open(
        self, *, test_id: uuid.UUID, variant_id: uuid.UUID, activated_at: datetime
    ) -> object: ...

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None: ...


class _Stats(Protocol):
    """The attributed-day repository, as the runner uses it."""

    async def upsert_days(self, *, test_id: uuid.UUID, days: Sequence[AttributedDay]) -> int: ...

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int: ...


class _Tests(Protocol):
    """The test repository, as the runner uses it."""

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID | None) -> None: ...

    async def set_status(
        self,
        *,
        test: AbTest,
        status: AbTestStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None: ...


class _Installer(Protocol):
    """The WB installer, as the runner uses it."""

    async def install(self, *, nm_id: int, variant: AbTestVariant) -> None: ...


@dataclass(frozen=True)
class RotationOutcome:
    """What one pass did to one test."""

    test_id: uuid.UUID
    action: RotationAction
    days_attributed: int
    installed_variant_id: uuid.UUID | None


class RotationRunner:
    """Advances one test's rotation from stored advertising days."""

    def __init__(
        self,
        *,
        tests: _Tests,
        exposures: _Exposures,
        stats: _Stats,
        installer: _Installer,
        load_ad_days: AdDayLoader,
    ) -> None:
        """Wire the runner to its collaborators.

        Args:
            tests: Test repository, for the lifecycle writes.
            exposures: Exposure repository, the rotation's audit trail.
            stats: Attributed-day repository.
            installer: Puts a variant's image on the card.
            load_ad_days: Monitoring's ``load_ad_days_for_nm``, already bound to
                a session — the A/B module never calls fullstats itself, because
                the harvest already pays that endpoint's toll.
        """
        self._tests = tests
        self._exposures = exposures
        self._stats = stats
        self._installer = installer
        self._load_ad_days = load_ad_days

    async def advance(self, test: AbTest, *, through: date) -> RotationOutcome:
        """Attribute advertising up to ``through`` and rotate if due.

        Args:
            test: A running test with its variants loaded.
            through: Last day to read; callers pass yesterday, since WB serves
                no data for the current day.

        Returns:
            What the pass did.

        Raises:
            IntegrationError: If WB refuses the new photo. The test is left
                untouched, and the next pass retries.
        """
        windows = await self._exposures.windows_for_test(test_id=test.id)
        attributed = await self._attribute(test, windows=windows, through=through)

        variant_ids = [variant.id for variant in test.variants]
        impressions = (
            await self._stats.impressions_for_variant(variant_id=test.active_variant_id)
            if test.active_variant_id is not None
            else 0
        )

        decision = decide(
            RotationState(
                active_variant_id=test.active_variant_id,
                variant_ids=variant_ids,
                impressions_for_active=impressions,
                impression_budget=test.impression_budget,
            )
        )

        installed: uuid.UUID | None = None
        if decision.action in {RotationAction.INSTALL, RotationAction.ADVANCE}:
            installed = await self._swap(test, variant_id=decision.variant_id)
        elif decision.action is RotationAction.COMPLETE:
            await self._complete(test)

        return RotationOutcome(
            test_id=test.id,
            action=decision.action,
            days_attributed=attributed,
            installed_variant_id=installed,
        )

    async def _attribute(
        self, test: AbTest, *, windows: Sequence[ExposureWindow], through: date
    ) -> int:
        """Store every whole day the rotation can credit to a variant."""
        if not windows:
            return 0

        start = min(window.activated_at for window in windows).date()
        floor = through - timedelta(days=LOOKBACK_DAYS)
        days = await self._load_ad_days(test.nm_id, max(start, floor), through)

        rows = attribute_days(days, windows=windows)
        return await self._stats.upsert_days(test_id=test.id, days=rows)

    async def _swap(self, test: AbTest, *, variant_id: uuid.UUID | None) -> uuid.UUID | None:
        """Install a variant, then record that it went up."""
        variant = next((item for item in test.variants if item.id == variant_id), None)
        if variant is None:  # pragma: no cover - decide() only names real variants
            return None

        # Upload first: everything below assumes the photo is actually on the
        # card, and an exception here must leave the test exactly as it was.
        await self._installer.install(nm_id=test.nm_id, variant=variant)

        now = datetime.now(UTC)
        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._exposures.open(test_id=test.id, variant_id=variant.id, activated_at=now)
        await self._tests.set_active_variant(test=test, variant_id=variant.id)

        logger.info(
            "ab_tests: nm %s rotated to variant %s (position %s)",
            test.nm_id,
            variant.id,
            variant.position,
        )
        return variant.id

    async def _complete(self, test: AbTest) -> None:
        """Close the last exposure and finish the test.

        The final photo stays on the card: taking it down would mean choosing a
        replacement, and the point of the test is that the seller makes that
        call from the results.
        """
        now = datetime.now(UTC)
        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._tests.set_status(test=test, status=AbTestStatus.COMPLETED, finished_at=now)
        logger.info("ab_tests: test %s completed on nm %s", test.id, test.nm_id)
