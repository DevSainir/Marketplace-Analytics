"""One polling pass over one test: close a window, then rotate if it is due.

Runs every few minutes without a request. The order inside a pass is the whole
design, and each step exists because of a specific way the alternative lies:

1. **Read, then close the window.** The traffic since the previous reading
   belongs to the photo that was live over that interval, so it is credited
   before anything changes — once per campaign that served the card, because
   two campaigns on one card are two separate measurements of it and adding
   them up before storing them throws that away for good.
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

**Nothing here ends a test.** The rotation is a circle (see :mod:`.rotation`)
and keeps going; when the advertising stops — switched off or out of money — the
test PAUSES and waits, and the sweep starts it again when a campaign serves. A
finished test is the seller's decision and only theirs, because every reason the
rotation could have for stopping is one they can undo in the WB seller portal.

The advertising is read **only when a swap is due**: at most once per slot rather
than once per pass, which keeps the check off a shallow rate bucket and gives the
photo that is up its full turn before anything reacts.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from src.core.logging import get_logger
from src.modules.ab_tests.models import AbTest, AbTestStatus, AbTestVariant
from src.modules.ab_tests.services.budget import AdsState
from src.modules.ab_tests.services.collection import (
    CampaignDays,
    Counters,
    campaign_deltas,
)
from src.modules.ab_tests.services.rotation import (
    RotationAction,
    RotationState,
    decide,
)

logger = get_logger(__name__)

#: Reads today's counters and, so a rollover closes cleanly, yesterday's too.
#: Answers per campaign: ``{campaign_id: {day: cumulative counters}}``.
CounterReader = Callable[[int, Sequence[date]], Awaitable[CampaignDays]]

#: Tells the register which campaigns this pass read counters from, so the page
#: can name them later. Takes the ids and the pass's clock.
CampaignRecorder = Callable[[Sequence[int], datetime], Awaitable[None]]

#: Asks what the advertising behind one card is doing. Called at most once
#: per slot — see the module docstring.
AdsReader = Callable[[int], Awaitable[AdsState]]

#: Asks the storefront when the card's main photo was last published, and — after
#: an install — waits for it to show ours. Two callables rather than the witness
#: itself because the URL comes from monitoring's catalogue, which this module
#: may not reach past its contract; the task wiring closes over it.
PhotoReader = Callable[[int], Awaitable[datetime | None]]
InstallConfirmer = Callable[[int, datetime | None], Awaitable[datetime | None]]


@dataclass(frozen=True)
class Snapshot:
    """The previous reading of a test's cumulative counters, per campaign."""

    captured_at: datetime
    by_campaign: CampaignDays


class _Snapshots(Protocol):
    """The snapshot repository, as the runner uses it."""

    async def load(self, *, test_id: uuid.UUID) -> Snapshot | None: ...

    async def save(
        self, *, test_id: uuid.UUID, by_campaign: CampaignDays, captured_at: datetime
    ) -> None: ...

    async def clear(self, *, test_id: uuid.UUID) -> None: ...


class _Windows(Protocol):
    """The window repository, as the runner uses it."""

    async def append(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        campaign_id: int,
        window_start: datetime,
        window_end: datetime,
        counters: Counters,
    ) -> None: ...

    async def impressions_for_variant(
        self, *, variant_id: uuid.UUID, since: datetime | None = None
    ) -> int: ...


class _Exposures(Protocol):
    """The exposure repository, as the runner uses it."""

    async def active_since(self, *, test_id: uuid.UUID) -> datetime | None: ...

    async def published_at_of_open(self, *, test_id: uuid.UUID) -> datetime | None: ...

    async def open(
        self,
        *,
        test_id: uuid.UUID,
        variant_id: uuid.UUID,
        activated_at: datetime,
        round_number: int,
        published_at: datetime | None = None,
    ) -> object: ...

    async def current_round(self, *, test_id: uuid.UUID) -> int: ...

    async def close_open(self, *, test_id: uuid.UUID, deactivated_at: datetime) -> None: ...


class _Tests(Protocol):
    """The test repository, as the runner uses it."""

    async def set_active_variant(self, *, test: AbTest, variant_id: uuid.UUID | None) -> None: ...

    async def pause_for_ads(self, *, test: AbTest, at: datetime) -> None: ...

    async def pause_for_photo_conflict(self, *, test: AbTest, at: datetime) -> None: ...

    async def set_status(
        self,
        *,
        test: AbTest,
        status: AbTestStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        stopped_at: datetime | None = None,
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
    #: True when this pass paused the test because nothing was advertising the
    #: card. Distinct from an ordinary HOLD, which is simply «the slot is not
    #: over yet» and is what most passes of a healthy test return.
    paused: bool = False
    seeded: bool = False
    #: True when this pass stopped the test because the card's main photo is
    #: not the one the rotation installed. Distinct from ``paused``: that one
    #: resumes by itself when the advertising does, and this one never does.
    photo_conflict: bool = False


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
        read_ads: AdsReader,
        read_counters: CounterReader,
        read_photo: PhotoReader,
        confirm_install: InstallConfirmer,
        remember_campaigns: CampaignRecorder,
    ) -> None:
        """Wire the runner to its collaborators.

        Args:
            tests: Test repository, for the lifecycle writes.
            exposures: Exposure repository, the rotation's audit trail.
            windows: Per-interval traffic repository.
            snapshots: Cumulative-counter memory between polls.
            installer: Puts a variant's image on the card.
            read_ads: Answers what the card's advertising is doing — serving,
                paused, or spent. Called only when a swap is due.
            read_photo: Asks the storefront when the card's main photo was last
                published. Answers ``None`` whenever it cannot tell, which
                skips the check rather than failing it.
            confirm_install: After an install, waits for the storefront to stop
                reporting the timestamp it was given and returns the new one.
            read_counters: Reads WB's cumulative counters for a SKU over the
                given days, split by campaign. Injected so the pass can be
                tested without WB and so the caller owns the shared rate budget.
            remember_campaigns: Records which campaigns this pass read, so the
                page can name them. Injected rather than resolved here because
                the names come from WB's campaign listing, which the task holds
                once for the whole workspace.
        """
        self._tests = tests
        self._exposures = exposures
        self._windows = windows
        self._snapshots = snapshots
        self._installer = installer
        self._read_counters = read_counters
        self._read_ads = read_ads
        self._read_photo = read_photo
        self._confirm_install = confirm_install
        self._remember_campaigns = remember_campaigns

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
        # BEFORE anything is credited. A window that closed over a card
        # somebody else had edited belongs to no variant of ours, and crediting
        # it and then pausing would leave exactly the wrong number behind.
        witnessed = await self._exposures.published_at_of_open(test_id=test.id)
        if witnessed is not None:
            live = await self._read_photo(test.nm_id)
            if live is not None and live != witnessed:
                await self._pause_with_photo_conflict(test, live=live, at=now)
                return PollOutcome(
                    test_id=test.id,
                    action=RotationAction.HOLD,
                    window_views=0,
                    installed_variant_id=None,
                    photo_conflict=True,
                )

        current = await self._read_counters(test.nm_id, days)
        previous = await self._snapshots.load(test_id=test.id)

        # Named before the windows are written, so a campaign that brought
        # nothing this pass is still on the page as one that is running.
        await self._remember_campaigns(sorted(current), now)

        seeded = previous is None
        window_views = 0
        if previous is not None and test.active_variant_id is not None:
            deltas = campaign_deltas(current=current, previous=previous.by_campaign)
            window_views = sum(delta.views for delta in deltas.values())
            for campaign_id, delta in deltas.items():
                # An empty delta is not a measurement — the campaign simply did
                # not move — and a row of zeroes would make "this ad campaign took
                # part in this lap" true of a campaign that served nothing.
                if delta.is_empty:
                    continue
                await self._windows.append(
                    test_id=test.id,
                    variant_id=test.active_variant_id,
                    campaign_id=campaign_id,
                    window_start=previous.captured_at,
                    window_end=now,
                    counters=delta,
                )

        # Move the baseline BEFORE any swap, so the next window starts where
        # this one ended and the rotation lands on the boundary between them.
        await self._snapshots.save(test_id=test.id, by_campaign=current, captured_at=now)

        active = next((v for v in test.variants if v.id == test.active_variant_id), None)
        # Read once and used twice: the clock the time trigger measures against
        # IS the boundary the impression budget counts from, because both ask
        # about the same thing — the turn the live photo is serving now.
        active_since = await self._exposures.active_since(test_id=test.id)
        decision = decide(
            RotationState(
                active_variant_id=test.active_variant_id,
                variant_ids=[v.id for v in test.variants if not v.is_excluded],
                trigger_mode=test.trigger_mode,
                impressions_for_active=(
                    await self._windows.impressions_for_variant(
                        variant_id=test.active_variant_id, since=active_since
                    )
                    if test.active_variant_id is not None
                    else 0
                ),
                impression_budget=test.impression_budget,
                active_since=active_since,
                slot_minutes=test.slot_minutes,
                now=now,
                active_is_excluded=active is not None and active.is_excluded,
            )
        )

        action = decision.action
        installed: uuid.UUID | None = None
        paused = False
        if action in {RotationAction.INSTALL, RotationAction.ADVANCE}:
            # The promise the seller was made: the photo that is up serves out
            # its turn, and only then does the rotation react. So the ads are
            # read at the swap, not on every pass.
            if await self._read_ads(test.nm_id) is AdsState.PAUSED:
                await self._pause_with_ads(test, now=now)
                action = RotationAction.HOLD
                paused = True
            else:
                installed = await self._swap(test, variant_id=decision.variant_id, now=now)

        return PollOutcome(
            test_id=test.id,
            action=action,
            window_views=window_views,
            installed_variant_id=installed,
            seeded=seeded,
            paused=paused,
        )

    async def _pause_with_ads(self, test: AbTest, *, now: datetime) -> None:
        """Stop advancing because nothing is advertising the card.

        Not a completion: the money is still there and the seller can switch the
        campaign back on, at which point the rotation picks up by itself. What
        it costs to get wrong is a table of zeros — a test that kept dealing
        photos through dead air would record each one's turn as no impressions,
        and ten such rows read exactly like a result.

        The counter snapshot is dropped so the pause cannot be paid for by the
        photo that happens to be up when the campaign returns: the baseline
        would be hours stale and the whole gap would land in one window. With no
        snapshot, the first pass after resuming seeds a fresh one and credits
        nothing, which is what a pause is supposed to mean.

        Args:
            test: The running test to pause.
            now: This pass's clock, recorded as when the test stopped.
        """
        await self._snapshots.clear(test_id=test.id)
        await self._tests.pause_for_ads(test=test, at=now)
        logger.info(
            "ab_tests: no running campaign on nm %s; test %s pauses with the advertising",
            test.nm_id,
            test.id,
        )

    async def _pause_with_photo_conflict(
        self, test: AbTest, *, live: datetime, at: datetime
    ) -> None:
        """Stop the test because the card is not showing our photo.

        Publication is same-second (measured 2026-09-10), so a main photo whose
        timestamp is not the one we witnessed at install was written by somebody
        who is not this rotation — in practice the seller, in the WB seller portal.
        From that moment the card's traffic belongs to a picture that is not in
        the comparison, and the honest thing to do with it is nothing.

        The snapshot is dropped for the same reason a pause drops it: the next
        pass must seed a fresh baseline rather than hand one variant everything
        that accumulated while the test was stopped.

        Args:
            test: The running test to stop.
            live: What the storefront reported, for the log.
            at: This pass's clock.
        """
        await self._snapshots.clear(test_id=test.id)
        await self._tests.pause_for_photo_conflict(test=test, at=at)
        logger.warning(
            "ab_tests: nm %s shows a main photo published %s, which test %s did not install; "
            "stopping rather than crediting it",
            test.nm_id,
            live.isoformat(),
            test.id,
        )

    async def _swap(
        self, test: AbTest, *, variant_id: uuid.UUID | None, now: datetime
    ) -> uuid.UUID | None:
        """Install a variant, then record that it went up.

        The round advances when the rotation comes back to the photo that leads
        it — the first one still in the rotation. Counting laps that way rather
        than dividing turns by photos survives a photo being excluded or added
        mid-test, which is exactly when the two answers differ.
        """
        variant = next((item for item in test.variants if item.id == variant_id), None)
        if variant is None:  # pragma: no cover - decide() only names real variants
            return None

        # What the storefront was showing before we touched it, so the
        # confirmation below can tell our own install from the previous photo.
        was = await self._read_photo(test.nm_id)

        # Upload first: everything below assumes the photo is actually on the
        # card, and an exception here must leave the test exactly as it was.
        await self._installer.install(nm_id=test.nm_id, variant=variant)

        # Then read back when the storefront says it published ours. This is
        # the witness every later pass checks the card against; ``None`` means
        # the turn is unwitnessed, which disables the check rather than arming
        # it with a value that would report a conflict against our own photo.
        published_at = await self._confirm_install(test.nm_id, was)

        leader = next((v for v in test.variants if not v.is_excluded), None)
        current = await self._exposures.current_round(test_id=test.id)
        # The very first install opens round 1; coming back round to the leader
        # opens the next one.
        round_number = 1 if current == 0 else current + (1 if leader is variant else 0)

        await self._exposures.close_open(test_id=test.id, deactivated_at=now)
        await self._exposures.open(
            test_id=test.id,
            variant_id=variant.id,
            activated_at=now,
            round_number=round_number,
            published_at=published_at,
        )
        await self._tests.set_active_variant(test=test, variant_id=variant.id)

        logger.info(
            "ab_tests: nm %s rotated to variant %s (position %s, round %s, trigger %s)",
            test.nm_id,
            variant.id,
            variant.position,
            round_number,
            test.trigger_mode,
        )
        return variant.id
