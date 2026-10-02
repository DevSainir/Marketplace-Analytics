"""The rules that turn two observations of a review into an event. Pure.

Kept apart from the walk so each rule is pinned by a unit test rather than
inferred from a database fixture: which change is an event, which is only new
state, and when a walk may declare reviews gone.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from src.integrations.wildberries.schemas import WBFeedback, WBStorefrontRating
from src.modules.monitoring.models import ReviewEventKind
from src.modules.monitoring.repos import EventDraft, KnownReview

#: Below this many, missing reviews are always believed.
VANISH_FLOOR = 25

#: Above this share of the live reviews, missing ones are NOT believed. WB
#: removing two per cent of a кабинет's reviews in one day is not moderation, it
#: is an answer that stopped short — a list WB truncated, an offset that jumped
#: — and recording it would bury the real disappearances under a false wave.
VANISH_MAX_SHARE = 0.02


def diff_listed(items: Sequence[WBFeedback], known: Mapping[str, KnownReview]) -> list[EventDraft]:
    """Events for the reviews on one page that were already on record.

    A review we have never seen produces nothing: its arrival is its
    ``first_seen_on``, and a row per arrival would only repeat that.

    Args:
        items: One page of the review list.
        known: What earlier walks recorded about those ids.

    Returns:
        RETURNED for a review recorded as vanished, RESCORED for a changed
        score, REPLACED when the buyer has replaced it since — each that
        applies, in that order.
    """
    drafts: list[EventDraft] = []
    for item in items:
        before = known.get(item.id)
        if before is None:
            continue
        if before.vanished_on is not None:
            drafts.append(
                EventDraft(
                    review_id=item.id,
                    nm_id=item.product.nm_id,
                    imt_id=item.product.imt_id,
                    kind=ReviewEventKind.RETURNED,
                    old_valuation=before.valuation,
                    new_valuation=item.valuation,
                    detail=f"vanished {before.vanished_on.isoformat()}",
                )
            )
        if before.valuation != item.valuation:
            drafts.append(
                EventDraft(
                    review_id=item.id,
                    nm_id=item.product.nm_id,
                    imt_id=item.product.imt_id,
                    kind=ReviewEventKind.RESCORED,
                    old_valuation=before.valuation,
                    new_valuation=item.valuation,
                )
            )
        if item.child_feedback_id and not before.child_review_id:
            drafts.append(
                EventDraft(
                    review_id=item.id,
                    nm_id=item.product.nm_id,
                    imt_id=item.product.imt_id,
                    kind=ReviewEventKind.REPLACED,
                    old_valuation=item.valuation,
                    detail=item.child_feedback_id,
                )
            )
    return drafts


def exclusions_seen(rating: WBStorefrontRating) -> dict[str, tuple[bool, str]]:
    """The exclusion flag of every storefront item that carried one.

    An item without ``excludedFromRating`` says nothing either way and is left
    out — as is every review the partial list did not include at all.
    """
    return {
        item.id: (item.excluded.is_excluded, ",".join(item.excluded.reasons))
        for item in rating.feedbacks or []
        if item.excluded is not None
    }


def diff_exclusions(
    seen: Mapping[str, tuple[bool, str]],
    known: Mapping[str, KnownReview],
    *,
    baseline: bool,
) -> tuple[list[EventDraft], dict[str, tuple[bool, str]]]:
    """Events and state changes from one storefront read of a склейка.

    Args:
        seen: :func:`exclusions_seen` of the read.
        known: Our record of those ids; ids we hold no row for are ignored.
        baseline: The first read of this склейка ever. Its flags become state
            and nothing else, because «excluded» on a first read says nothing
            about WHEN — and dating it to today would place it beside whatever
            else today brought.

    Returns:
        ``(drafts, changes)`` — EXCLUDED when a review we did not know to be
        excluded now is, INCLUDED when one we knew excluded no longer is; and
        every id whose stored flag must change.
    """
    drafts: list[EventDraft] = []
    changes: dict[str, tuple[bool, str]] = {}
    for review_id, (excluded, reasons) in seen.items():
        before = known.get(review_id)
        if before is None or before.excluded is excluded:
            continue
        changes[review_id] = (excluded, reasons)
        if baseline:
            continue
        if excluded:
            kind = ReviewEventKind.EXCLUDED
        elif before.excluded:
            kind = ReviewEventKind.INCLUDED
        else:
            continue
        drafts.append(
            EventDraft(
                review_id=review_id,
                nm_id=before.nm_id,
                imt_id=before.imt_id,
                kind=kind,
                old_valuation=before.valuation,
                detail=reasons,
            )
        )
    return drafts, changes


def vanishing_is_believable(missing: int, live: int) -> bool:
    """Whether a walk's missing reviews may be recorded as vanished.

    Args:
        missing: Live reviews the complete walk did not list.
        live: Live reviews on record before the walk.

    Returns:
        ``True`` up to :data:`VANISH_FLOOR`, or up to :data:`VANISH_MAX_SHARE`
        of ``live`` when that is more.
    """
    return missing <= max(VANISH_FLOOR, int(live * VANISH_MAX_SHARE))


def snapshot_row(
    rating: WBStorefrontRating,
    *,
    workspace_id: uuid.UUID,
    imt_id: int,
    snapshot_date: date,
    seller_api_count: int,
) -> dict[str, Any]:
    """The ``rating_snapshot`` row for one склейка's read."""
    return {
        "snapshot_date": snapshot_date,
        "workspace_id": workspace_id,
        "imt_id": imt_id,
        "valuation": rating.valuation,
        "valuation_sum": rating.valuation_sum,
        "feedback_count": rating.feedback_count,
        "stars_1": rating.stars(1),
        "stars_2": rating.stars(2),
        "stars_3": rating.stars(3),
        "stars_4": rating.stars(4),
        "stars_5": rating.stars(5),
        "nm_distribution": rating.nm_distribution,
        "seller_api_count": seller_api_count,
    }


__all__ = [
    "VANISH_FLOOR",
    "VANISH_MAX_SHARE",
    "diff_exclusions",
    "diff_listed",
    "exclusions_seen",
    "snapshot_row",
    "vanishing_is_believable",
]
