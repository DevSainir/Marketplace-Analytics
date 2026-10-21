"""Which changes to a review become an event, and when missing reviews count as gone.

These rules are what the review history is for: on 2026-10-02 a card went
4.6 → 4.7 as one 5★ arrived, which only makes sense if two or three negative
reviews left the count in the same moment — and nothing on record could show it.
Each rule below is one way that question gets a wrong answer if it slips: an
event per arrival buries the real ones, a first storefront read dated as a fresh
exclusion invents a moderation that never happened, and a walk that stopped
short reports thousands of reviews «vanished».
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from src.integrations.wildberries.schemas import WBFeedback, WBStorefrontRating
from src.modules.monitoring.models import ReviewEventKind
from src.modules.monitoring.repos import KnownReview
from src.modules.monitoring.services.reviews import (
    diff_exclusions,
    diff_listed,
    exclusions_seen,
    snapshot_row,
    vanishing_is_believable,
)

pytestmark = pytest.mark.unit

TODAY = date(2026, 10, 2)


def make_review(review_id: str, valuation: int, *, child: str | None = None) -> WBFeedback:
    """A review as the seller API lists it, on nm 953770957 / imt 7001."""
    payload: dict[str, Any] = {
        "id": review_id,
        "productValuation": valuation,
        "createdDate": "2026-09-30T10:00:00Z",
        "parentFeedbackId": None,
        "childFeedbackId": child,
        "productDetails": {"nmId": 953770957, "imtId": 7001, "supplierArticle": "M-TRX01-BLK"},
        "text": "a text the history never stores",
    }
    return WBFeedback.model_validate(payload)


def known(
    valuation: int,
    *,
    vanished_on: date | None = None,
    child: str | None = None,
    excluded: bool | None = None,
) -> KnownReview:
    """What an earlier walk recorded about a review on the same card."""
    return KnownReview(
        nm_id=953770957,
        imt_id=7001,
        valuation=valuation,
        child_review_id=child,
        vanished_on=vanished_on,
        excluded=excluded,
    )


def test_a_review_never_seen_before_is_state_not_an_event() -> None:
    """An arrival is its ``first_seen_on``; a row per arrival would only repeat it."""
    drafts = diff_listed([make_review("new", 5)], known={})

    assert drafts == []


def test_an_unchanged_review_produces_nothing() -> None:
    """Overlapping pages re-read reviews; a re-read must be silent."""
    drafts = diff_listed([make_review("a", 5)], known={"a": known(5)})

    assert drafts == []


def test_a_changed_score_is_a_rescore_with_both_values() -> None:
    """A buyer editing 1★ to 4★ moves the mean as much as a new review does."""
    drafts = diff_listed([make_review("a", 4)], known={"a": known(1)})

    assert [(d.kind, d.old_valuation, d.new_valuation) for d in drafts] == [
        (ReviewEventKind.RESCORED, 1, 4)
    ]


def test_a_vanished_review_listed_again_is_a_return() -> None:
    """A false «vanished» must be visible as such the day it is undone."""
    drafts = diff_listed(
        [make_review("a", 2)], known={"a": known(2, vanished_on=date(2026, 9, 30))}
    )

    assert [(d.kind, d.detail) for d in drafts] == [
        (ReviewEventKind.RETURNED, "vanished 2026-09-30")
    ]


def test_a_review_the_buyer_replaced_is_recorded_once() -> None:
    """WB stops counting a replaced review — the count drops without a deletion."""
    first = diff_listed([make_review("a", 1, child="b")], known={"a": known(1)})
    again = diff_listed([make_review("a", 1, child="b")], known={"a": known(1, child="b")})

    assert [(d.kind, d.old_valuation, d.detail) for d in first] == [
        (ReviewEventKind.REPLACED, 1, "b")
    ]
    assert again == []


def _rating(items: list[dict[str, Any]]) -> WBStorefrontRating:
    return WBStorefrontRating.model_validate({"valuation": "4.7", "feedbacks": items})


def test_only_storefront_items_carrying_the_flag_say_anything() -> None:
    """The storefront list is partial; an item without the flag is not «included»."""
    rating = _rating(
        [
            {"id": "a", "excludedFromRating": {"isExcluded": True, "reasons": ["notProduct"]}},
            {"id": "b", "excludedFromRating": {"isExcluded": False, "reasons": []}},
            {"id": "c"},
        ]
    )

    assert exclusions_seen(rating) == {"a": (True, "notProduct"), "b": (False, "")}


def test_a_first_read_of_a_card_records_exclusions_without_dating_them() -> None:
    """«Excluded» on a first read says nothing about when; dating it today would lie."""
    drafts, changes = diff_exclusions({"a": (True, "notProduct")}, {"a": known(1)}, baseline=True)

    assert drafts == []
    assert changes == {"a": (True, "notProduct")}


def test_a_review_newly_excluded_by_wb_is_an_event() -> None:
    """The moderation that moves a rating without deleting anything."""
    drafts, changes = diff_exclusions(
        {"a": (True, "notProduct")}, {"a": known(1, excluded=False)}, baseline=False
    )

    assert [(d.kind, d.old_valuation, d.detail) for d in drafts] == [
        (ReviewEventKind.EXCLUDED, 1, "notProduct")
    ]
    assert changes == {"a": (True, "notProduct")}


def test_a_review_wb_counts_again_is_an_inclusion() -> None:
    drafts, _ = diff_exclusions({"a": (False, "")}, {"a": known(2, excluded=True)}, baseline=False)

    assert [d.kind for d in drafts] == [ReviewEventKind.INCLUDED]


def test_learning_a_review_is_counted_is_state_not_an_event() -> None:
    """Unknown → counted is what WB always did; nothing happened to the rating."""
    drafts, changes = diff_exclusions({"a": (False, "")}, {"a": known(2)}, baseline=False)

    assert drafts == []
    assert changes == {"a": (False, "")}


def test_a_storefront_review_we_hold_no_row_for_is_ignored() -> None:
    drafts, changes = diff_exclusions({"stranger": (True, "x")}, {}, baseline=False)

    assert (drafts, changes) == ([], {})


def test_a_handful_of_missing_reviews_is_always_believed() -> None:
    """A small workspace losing three reviews to a complaint is the case this is for."""
    assert vanishing_is_believable(missing=3, live=40)


def test_a_mass_disappearance_is_not_believed() -> None:
    """Ten thousand «vanished» in a day is a walk that stopped short, not moderation."""
    assert not vanishing_is_believable(missing=10_000, live=150_000)


def test_a_large_account_may_lose_up_to_its_share() -> None:
    assert vanishing_is_believable(missing=2_000, live=150_000)


def test_a_snapshot_row_carries_the_distribution_and_the_unrounded_sum() -> None:
    """The sum over the count is what places a 4.6 → 4.7 flip to the review."""
    rating = WBStorefrontRating.model_validate(
        {
            "valuation": "4.7",
            "valuationSum": 4136,
            "feedbackCount": 880,
            "valuationDistribution": {"1": 20, "2": 10, "3": 10, "5": 840},
        }
    )

    row = snapshot_row(
        rating,
        workspace_id=uuid.uuid4(),
        imt_id=7001,
        snapshot_date=TODAY,
        seller_api_count=878,
    )

    assert (row["valuation"], row["valuation_sum"], row["feedback_count"]) == (
        Decimal("4.7"),
        4136,
        880,
    )
    assert [row[f"stars_{n}"] for n in range(1, 6)] == [20, 10, 10, 0, 840]
    assert row["seller_api_count"] == 878


def test_a_card_with_no_counted_review_has_no_rating_rather_than_zero() -> None:
    """A 0.0 would read as the worst possible card."""
    rating = WBStorefrontRating.model_validate({"valuation": "", "feedbackCount": 0})

    assert rating.valuation is None


def test_a_blank_replacement_link_means_none() -> None:
    """WB writes «no link» as ``""`` on some rows; read as a link it fakes a replacement."""
    review = make_review("a", 5, child="")

    assert review.child_feedback_id is None
    assert review.created_date == datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
