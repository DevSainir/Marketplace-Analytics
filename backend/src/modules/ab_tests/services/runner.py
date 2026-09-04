"""One polling pass over one test: close a window, then rotate if it is due.

Runs every few minutes without a request. The order inside a pass is the whole
design, and each step exists because of a specific way the alternative lies:

1. **Read, then close the window.** The traffic since the previous reading
   belongs to the photo that was live over that interval, so it is credited
   before anything changes.
2. **Snapshot immediately.** The new reading becomes the baseline, so the next
   window starts exactly where this one ended and nothing is double-counted.
3. **Then decide, and swap last.** Because the swap happens after the window is
   closed and the baseline is moved, a rotation always lands on a window
   boundary — which is why a photo can turn over several times a day without
   any interval being split between two variants.
4. **Install, and only then record.** The exposure row and the active-variant
   pointer are written after WB accepts the upload, never before. A pointer that
   moved on a failed upload would credit every following window to a picture
   that is not on the card.

A test with no snapshot yet gets one and no window: without that rule, a test
started at noon would credit its first photo with everything the card earned
since midnight.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from src.core.logging import get_logger
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.collection import Counters, window_delta
from src.modules.ab_tests.services.rotation import (
    RotationAction,
    RotationState,
    decide,
)

logger = get_logger(__name__)

#: Reads today's counters and, so a rollover closes cleanly, yesterday's too.
CounterReader = Callable[[int, Sequence[date]], Awaitable[dict[date, Counters]]]


@dataclass(frozen=True)
class Snapshot:
    """The previous reading of a test's cumulative counters."""

    captured_at: datetime
    by_day: dict[date, Counters]


class _Snapshots(Protocol):
    """The snapshot repository, as the runner uses it."""

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None: ...

    async def save(
        self, *, test_id: uuid.UUID, by_day: dict[date, Counters], captured_at: datetime
    ) -> None: ...


class _Windows(Protocol):
    """The window repository, as the runner uses it."""

    async def append(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None: ...

    async def impressions_for_variant(self, *, variant_id: uuid.UUID) -> int: ...


class _Exposures(Protocol):
    """The exposure repository, as the runner uses it."""

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None: ...

    async def open(
        self, *, test_id: uuid.UUID, variant_id: uuid.UUID, activated_at: datetime
    ) -> object: ...

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None: ...


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
class PollOutcome:
    """What one pass did to one test."""

    test_id: uuid.UUID
    action: RotationAction
    window_views: int
    installed_variant_id: uuid.UUID | None
    seeded: bool = False


class RotationRunner:
    """Advances one test's rotation from live advertising counters."""

    def __init__(
        self,
        *,
        tests: _Tests,
        exposures: _Exposures,
        windows: _Windows,
        snapshots: _Snapshots,
        installer: _Installer,
        read_counters: CounterReader,
    ) -> None:
        """Wire the runner to its collaborators.

        Args:
            tests: Test repository, for the lifecycle writes.
            exposures: Exposure repository, the rotation's audit trail.
            windows: Per-interval traffic repository.
            snapshots: Cumulative-counter memory between polls.
            installer: Puts a variant's image on the card.
            read_counters: Reads WB's cumulative counters for a SKU over the
                given days. Injected so the pass can be tested without WB and
                so the caller owns the shared rate budget.
        """
        self._tests = tests
        self._exposures = exposures
        self._windows = windows
        self._snapshots = snapshots
        self._installer = installer
        self._read_counters = read_counters

    async def poll(self, test: AbTest, *, days: Sequence[date], now: datetime) -> PollOutcome:
        """Close the interval since the last poll and rotate if it is due.

        Args:
            test: A running test with its variants loaded.
            days: Advertising days to read — today, plus enough history to
                close a midnight rollover.
            now: The moment of this poll; bounds the window it closes.

        Returns:
            What the pass did.

        Raises:
            IntegrationError: If WB refuses the new photo. The test is left
                untouched, and the next poll retries.
        """
        current = await self._read_counters(test.nm_id, days)
        previous = await self._snapshots.load(test_id=test.id)

        seeded = previous is None
        window_views = 0
        if previous is not None and test.active_variant_id is not None:
            delta = window_delta(current=current, previous=previous.by_day)
            window_views = delta.views
            if not delta.is_empty:
                await self._windows.append(
                    test_id=test.id,
                    variant_id=test.active_variant_id,
                    window_start=previous.captured_at,
                    window_end=now,
                    counters=delta,
                )

        # Move the baseline BEFORE any swap, so the next window starts where
        # this one ended and the rotation lands on the boundary between them.
        await self._snapshots.save(test_id=test.id, by_day=current, captured_at=now)

        decision = decide(
            RotationState(
                active_variant_id=test.active_variant_id,
                variant_ids=[variant.id for variant in test.variants],
                trigger_mode=test.trigger_mode,
                impressions_for_active=(
                    await self._windows.impressions_for_variant(variant_id=test.active_variant_id)
                    if test.active_variant_id is not None
                    else 0
                ),
                impression_budget=test.impression_budget,
                active_since=await self._exposures.active_since(test_id=test.id),
                slot_minutes=test.slot_minutes,
                now=now,
            )
        )

        installed: uuid.UUID | None = None
        if decision.action in {RotationAction.INSTALL, RotationAction.ADVANCE}:
            installed = await self._swap(test, variant_id=decision.variant_id, now=now)
        elif decision.action is RotationAction.COMPLETE:
            await self._complete(test, now=now)

        return PollOutcome(
            test_id=test.id,
            action=decision.action,
            window_views=window_views,
            installed_variant_id=installed,
            seeded=seeded,
        )

    async def _swap(
        self, test: AbTest, *, variant_id: uuid.UUID | None, now: datetime
    ) -> uuid.UUID | None:
        """Install a variant, then record that it went up."""
        variant = next((item for item in test.variants if item.id == variant_id), None)
        if variant is None:  # pragma: no cover - decide() only names real variants
            return None

        # Upload first: everything below assumes the photo is actually on the
        # card, and an exception here must leave the test exactly as it was.
        await self._installer.install(nm_id=test.nm_id, variant=variant)

        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._exposures.open(test_id=test.id, variant_id=variant.id, activated_at=now)
        await self._tests.set_active_variant(test=test, variant_id=variant.id)

        logger.info(
            "ab_tests: nm %s rotated to variant %s (position %s, trigger %s)",
            test.nm_id,
            variant.id,
            variant.position,
            test.trigger_mode,
        )
        return variant.id

    async def _complete(self, test: AbTest, *, now: datetime) -> None:
        """Close the last exposure and finish the test.

        The final photo stays on the card: taking it down would mean choosing a
        replacement, and the point of the test is that the seller makes that
        call from the results.
        """
        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._tests.set_status(
            test=test, status=AbTestStatus.COMPLETED, finished_at=now or datetime.now(UTC)
        )
        logger.info("ab_tests: test %s completed on nm %s", test.id, test.nm_id)
