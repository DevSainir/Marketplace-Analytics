"""Reviews: the seller feedbacks API and the public storefront's rating summary.

Two sources answer two different questions, and neither answers both:

* The seller API (``feedbacks-api.wildberries.ru/api/v1/feedbacks``) lists every
  review that still EXISTS — so it can show a score edit or a replacement, and,
  by absence on a later walk, a disappearance. It says nothing about whether WB
  counts a review in the card's rating.
* The storefront (``feedbacks1.wb.ru/feedbacks/v2/{imtId}``) carries the rating
  itself — ``valuation``, ``valuationSum`` and the score distribution over the
  card group, which are complete — and a PARTIAL list of reviews (456 of 1259 on
  the card that prompted this, skewed toward text reviews) whose items say whether WB
  excludes each one from the rating. Never average that list.

Only the fields the review history reads are modelled; WB's text, photos and
answers are dropped at the boundary, which is also what keeps a 5000-review
page's footprint small once parsed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from src.integrations.wildberries.schemas.base import RawBase


class WBFeedbackProduct(RawBase):
    """``productDetails`` of a review: which card it was left on."""

    nm_id: int = Field(alias="nmId")
    imt_id: int = Field(default=0, alias="imtId")


class WBFeedback(RawBase):
    """One review as the seller API lists it.

    ``child_feedback_id`` is set when the buyer later REPLACED this review with
    another one: the old review stays listed, and WB stops counting it — the
    2026-10-02 reconciliation matched WB's per-nm distribution only after
    dropping these.
    """

    id: str = Field(min_length=1, max_length=64)
    valuation: int = Field(alias="productValuation", ge=0, le=5)
    created_date: datetime = Field(alias="createdDate")
    parent_feedback_id: str | None = Field(default=None, alias="parentFeedbackId", max_length=64)
    child_feedback_id: str | None = Field(default=None, alias="childFeedbackId", max_length=64)
    product: WBFeedbackProduct = Field(alias="productDetails")

    @field_validator("parent_feedback_id", "child_feedback_id", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        """WB writes «no link» as ``null`` and, on some rows, as ``""``."""
        return value or None


class WBStorefrontExclusion(RawBase):
    """``excludedFromRating`` on a storefront review item."""

    is_excluded: bool = Field(default=False, alias="isExcluded")
    reasons: list[str] = Field(default_factory=list, max_length=16)


class WBStorefrontFeedback(RawBase):
    """A storefront review item, reduced to whether WB counts it."""

    id: str = Field(min_length=1, max_length=64)
    excluded: WBStorefrontExclusion | None = Field(default=None, alias="excludedFromRating")


class WBStorefrontRating(RawBase):
    """The storefront's rating summary for one card group (``imtId``).

    ``valuation`` is WB's rounded stars — the plain mean of the counted scores,
    rounded half-up to 0.1 (31/31 cards, 2026-10-02). ``valuation_sum`` over the
    distribution's total is the unrounded mean, which is what makes a 4.6 → 4.7
    flip explainable to the review.
    """

    valuation: Decimal | None = None
    valuation_sum: int = Field(default=0, alias="valuationSum", ge=0)
    feedback_count: int = Field(default=0, alias="feedbackCount", ge=0)
    distribution: dict[str, int] = Field(default_factory=dict, alias="valuationDistribution")
    # Per-nm distributions, kept as WB serves them: the shape has been seen once
    # and is not interpreted here.
    nm_distribution: dict[str, Any] | list[Any] | None = Field(
        default=None, alias="nmValuationDistribution"
    )
    feedbacks: list[WBStorefrontFeedback] | None = None

    @field_validator("valuation", mode="before")
    @classmethod
    def _blank_valuation_is_none(cls, value: Any) -> Any:
        """A card with no counted review answers ``""`` or ``0``, not a rating."""
        if value in ("", None, 0, "0"):
            return None
        return value

    def stars(self, score: int) -> int:
        """How many counted reviews gave ``score`` stars (0 when WB omitted it)."""
        return int(self.distribution.get(str(score), 0) or 0)


__all__ = [
    "WBFeedback",
    "WBFeedbackProduct",
    "WBStorefrontExclusion",
    "WBStorefrontFeedback",
    "WBStorefrontRating",
]
