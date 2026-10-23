"""One workspace's daily review history: walk the review list, then read the ratings.

Two phases, in this order because the second needs the first's card groups:

1. **The walk.** Both halves of the seller review list (unanswered, then
   answered), oldest first, one page at a time: each page is diffed against
   what is on record, upserted, and committed before the next is asked for. A
   ~150k-review workspace is therefore never in memory — one page is — and a walk
   cut short keeps every page before the cut.

   Unanswered first: a review answered DURING the walk then moves into the half
   still to be read, rather than out of the one already read. Pages overlap by
   :data:`PAGE_OVERLAP` for the same reason — a review leaving an earlier
   position shifts every later offset back, and without the overlap the review
   that slid across the page boundary would be skipped and, the next day,
   reported as vanished.

   Only a COMPLETE walk may declare reviews vanished — every page read, every
   item parsed — and only as many as :func:`vanishing_is_believable` allows.
   Anything less, and "not listed" means "not read".

2. **The ratings.** The storefront summary of every card group (WB's merged card) the
   workspace's reviews name, one at a time on a shared, slow bucket, each committed on its
   own. A storefront that refuses three in a row is treated as refusing the
   rest: the day's ratings are lost either way, and asking on is how an
   unauthenticated reader gets its address blocked.

No transaction is open across a WB call: each page and each card group is read
first, then written and committed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger
from src.integrations.wildberries.clients import FeedbackPage
from src.integrations.wildberries.schemas import WBFeedback, WBStorefrontRating
from src.modules.monitoring.repos import ReviewRepository
from src.modules.monitoring.services.reviews.diff import (
    diff_exclusions,
    diff_listed,
    exclusions_seen,
    snapshot_row,
    vanishing_is_believable,
)

logger = get_logger(__name__)

#: Reviews per page. Well under WB's 5000: a page is the walk's whole memory
#: footprint, and a thousand parsed reviews is a few megabytes.
PAGE_SIZE = 1000

#: Reviews each page re-reads from the end of the previous one (see the module
#: docstring). Re-reading is free — the upsert lands on itself.
PAGE_OVERLAP = 50

#: The deepest offset the walk asks for. WB documents ``skip`` up to 199 990;
#: a half of the list longer than that is not walked to the end, and the walk
#: is incomplete rather than wrong.
MAX_SKIP = 199_000

#: Storefront refusals in a row after which the rest of the card groups are skipped.
STOREFRONT_GIVE_UP_AFTER = 3


class ReviewPages(Protocol):
    """The seller review list: ``WBFeedbacksClient``."""

    async def fetch_page(self, *, answered: bool, take: int, skip: int) -> FeedbackPage:
        """One page of one half of the list, oldest first."""
        ...


class RatingReader(Protocol):
    """The storefront summary: ``WBStorefrontFeedbacksClient``."""

    async def fetch_rating(self, imt_id: int) -> WBStorefrontRating | None:
        """One card group's rating summary."""
        ...


@dataclass(slots=True)
class HistoryResult:
    """What one workspace's run did."""

    listed: int = 0
    events: int = 0
    vanished: int = 0
    complete: bool = True
    vanish_refused: int = 0
    snapshots: int = 0
    storefront_failures: int = 0
    notes: list[str] = field(default_factory=list)


class ReviewHistory:
    """Runs both phases for one workspace."""

    def __init__(
        self,
        repo: ReviewRepository,
        *,
        commit: Callable[[], Awaitable[None]],
        feedbacks: ReviewPages,
        storefront: RatingReader,
        workspace_id: uuid.UUID,
        today: date,
    ) -> None:
        """Bind the collaborators for one workspace and one day.

        Args:
            repo: Review persistence on the caller's session.
            commit: Commits that session; called after every page and card group.
            feedbacks: The workspace's seller review client.
            storefront: The shared public storefront client.
            workspace_id: The workspace.
            today: The Moscow date every observation is filed under.
        """
        self._repo = repo
        self._commit = commit
        self._feedbacks = feedbacks
        self._storefront = storefront
        self._workspace_id = workspace_id
        self._today = today

    async def run(self) -> HistoryResult:
        """Walk the reviews, then snapshot the ratings.

        The storefront phase runs even when the walk failed part-way: the
        rating snapshot does not depend on it, and the card groups come from what
        earlier walks recorded as well as this one.
        """
        result = HistoryResult()
        try:
            await self._walk(result)
        except IntegrationError as exc:
            result.complete = False
            result.notes.append(f"walk: {exc}")
            logger.warning("Review walk stopped early: %s", exc)
        else:
            if result.complete:
                await self._settle_vanished(result)
        await self._snapshot_ratings(result)
        return result

    async def _walk(self, result: HistoryResult) -> None:
        """Read both halves of the review list into ``review_state``."""
        for answered in (False, True):
            skip = 0
            while True:
                if skip > MAX_SKIP:
                    result.complete = False
                    result.notes.append(f"answered={answered}: deeper than skip {MAX_SKIP}")
                    break
                page = await self._feedbacks.fetch_page(
                    answered=answered, take=PAGE_SIZE, skip=skip
                )
                if page.malformed:
                    result.complete = False
                await self._absorb(page.items, result)
                if page.received < PAGE_SIZE:
                    break
                skip += page.received - PAGE_OVERLAP

    async def _absorb(self, items: list[WBFeedback], result: HistoryResult) -> None:
        """Diff one page against the record, store it, commit."""
        if not items:
            return
        known = await self._repo.known(
            workspace_id=self._workspace_id, review_ids={item.id for item in items}
        )
        drafts = diff_listed(items, known)
        await self._repo.record_seen(
            workspace_id=self._workspace_id, items=items, seen_on=self._today
        )
        result.events += await self._repo.add_events(
            workspace_id=self._workspace_id, observed_on=self._today, drafts=drafts
        )
        result.listed += len(items)
        await self._commit()

    async def _settle_vanished(self, result: HistoryResult) -> None:
        """Record the reviews a complete walk did not list, if believable."""
        missing = await self._repo.count_missing(
            workspace_id=self._workspace_id, walked_on=self._today
        )
        if missing == 0:
            return
        live = await self._repo.count_live(workspace_id=self._workspace_id)
        if not vanishing_is_believable(missing, live):
            result.vanish_refused = missing
            logger.warning(
                "Review walk missed %d of %d live reviews; not recording them as vanished.",
                missing,
                live,
            )
            return
        drafts = await self._repo.missing(workspace_id=self._workspace_id, walked_on=self._today)
        result.events += await self._repo.add_events(
            workspace_id=self._workspace_id, observed_on=self._today, drafts=drafts
        )
        await self._repo.mark_vanished(workspace_id=self._workspace_id, walked_on=self._today)
        result.vanished = len(drafts)
        await self._commit()

    async def _snapshot_ratings(self, result: HistoryResult) -> None:
        """Read and store every card group's storefront rating, one at a time."""
        refused_in_a_row = 0
        for imt_id in await self._repo.imt_ids(workspace_id=self._workspace_id):
            try:
                rating = await self._storefront.fetch_rating(imt_id)
            except IntegrationError as exc:
                result.storefront_failures += 1
                refused_in_a_row += 1
                if refused_in_a_row >= STOREFRONT_GIVE_UP_AFTER:
                    result.notes.append(f"storefront: gave up after {exc}")
                    logger.warning(
                        "Storefront refused %d card groups in a row; stopping.", refused_in_a_row
                    )
                    return
                continue
            refused_in_a_row = 0
            if rating is None:
                continue
            baseline = not await self._repo.has_snapshot(
                workspace_id=self._workspace_id, imt_id=imt_id
            )
            seen = exclusions_seen(rating)
            known = await self._repo.known(workspace_id=self._workspace_id, review_ids=seen.keys())
            drafts, changes = diff_exclusions(seen, known, baseline=baseline)
            await self._repo.set_exclusions(workspace_id=self._workspace_id, exclusions=changes)
            result.events += await self._repo.add_events(
                workspace_id=self._workspace_id, observed_on=self._today, drafts=drafts
            )
            counted = await self._repo.seller_api_count(
                workspace_id=self._workspace_id, imt_id=imt_id
            )
            written = await self._repo.add_snapshot(
                snapshot_row(
                    rating,
                    workspace_id=self._workspace_id,
                    imt_id=imt_id,
                    snapshot_date=self._today,
                    seller_api_count=counted,
                )
            )
            result.snapshots += int(written)
            await self._commit()


__all__ = [
    "MAX_SKIP",
    "PAGE_OVERLAP",
    "PAGE_SIZE",
    "STOREFRONT_GIVE_UP_AFTER",
    "HistoryResult",
    "RatingReader",
    "ReviewHistory",
    "ReviewPages",
]
