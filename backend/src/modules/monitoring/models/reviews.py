"""The review history: enough to explain a rating change after the fact.

Built after 2026-10-02, when M-TRX01-BLK went 4.6 → 4.7 at the moment one 5★
arrived. One 5★ moves an ~880-score mean by ~0.0003, so two or three negative
reviews must have left the count at the same moment — and nothing could prove
it: ``product_card.feedback_rating`` is overwritten nightly, and WB's review
list only shows reviews that still exist.

Three tables, and not a copy of every review per day:

* :class:`RatingSnapshot` — one row per склейка per day, append-only: the
  stars, the unrounded sum, the count and the distribution, so the day the
  rating flipped and by how much the count moved are both on record.
* :class:`ReviewState` — one row per review, upserted daily: what it scores
  now, when we first and last saw it, whether it has vanished. Arrivals are
  ``first_seen_on``; nothing else needs a row per day.
* :class:`ReviewEvent` — what changed about an EXISTING review: it vanished,
  came back, was rescored, replaced by the buyer, or excluded from (or
  re-included in) the rating by WB. Append-only.

Dated to the day of the walk that noticed. A review that vanished at 10:00 and a
rating that flipped at 10:00 land on the same ``observed_on`` — that is the
resolution, and it is enough to line the two up.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.ids import uuid7

_SCHEMA: str = "monitoring"

#: WB's review ids are 20-character strings today; room to spare.
REVIEW_ID_MAX_LENGTH: int = 64


class ReviewEventKind(enum.StrEnum):
    """What changed about a review that already existed."""

    #: Missing from a complete walk of both halves of the list.
    VANISHED = "vanished"
    #: Listed again after being recorded as vanished.
    RETURNED = "returned"
    #: Its score changed.
    RESCORED = "rescored"
    #: The buyer replaced it with another review; WB stops counting this one.
    REPLACED = "replaced"
    #: The storefront began marking it ``excludedFromRating``.
    EXCLUDED = "excluded"
    #: The storefront stopped marking it excluded.
    INCLUDED = "included"


class RatingSnapshot(Base):
    """One склейка's rating as the storefront showed it on one day.

    The first observation of a day stands: a second run the same day inserts
    nothing, so the row is what the day looked like when first asked.

    Attributes:
        snapshot_date: Moscow date of the observation.
        workspace_id: The кабинет whose reviews named this склейка.
        imt_id: The склейка — WB rates the склейка, not the article.
        valuation: WB's rounded stars, ``None`` when WB served none.
        valuation_sum: Sum of the counted scores; over the distribution's total
            it is the unrounded mean.
        feedback_count: WB's own review count for the склейка.
        stars_1..stars_5: The counted distribution.
        nm_distribution: The per-article distribution, verbatim.
        seller_api_count: Reviews of this склейка our own walk holds as live,
            unreplaced and not known to be excluded — set beside WB's count so a
            divergence between the two lists is visible the day it starts.
    """

    __tablename__ = "rating_snapshot"
    __table_args__ = ({"schema": _SCHEMA},)

    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    imt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    valuation: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    valuation_sum: Mapped[int] = mapped_column(BigInteger, nullable=False)
    feedback_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_1: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_2: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_3: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_4: Mapped[int] = mapped_column(Integer, nullable=False)
    stars_5: Mapped[int] = mapped_column(Integer, nullable=False)
    nm_distribution: Mapped[Any] = mapped_column(JSONB, nullable=True)
    seller_api_count: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewState(Base):
    """One review's latest known state.

    Attributes:
        workspace_id: Owning кабинет.
        review_id: WB's review id.
        nm_id / imt_id: The article and склейка it was left on.
        valuation: Its score now.
        created_at: When the buyer left it (WB's ``createdDate``).
        parent_review_id / child_review_id: The review it replaced, and the one
            that replaced it. A set ``child_review_id`` means WB no longer
            counts this one.
        first_seen_on / last_seen_on: The walks that first and last listed it.
        vanished_on: The walk that first found it missing; cleared if it
            returns.
        excluded: Whether the storefront marks it excluded from the rating —
            ``None`` until a storefront read happened to list it, because that
            list is partial and silence there means nothing.
        excluded_reasons: WB's reasons, comma-joined, as last seen.
    """

    __tablename__ = "review_state"
    __table_args__ = (
        Index("ix_review_state_workspace_imt", "workspace_id", "imt_id"),
        {"schema": _SCHEMA},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(String(REVIEW_ID_MAX_LENGTH), primary_key=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    valuation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    parent_review_id: Mapped[str | None] = mapped_column(
        String(REVIEW_ID_MAX_LENGTH), nullable=True
    )
    child_review_id: Mapped[str | None] = mapped_column(String(REVIEW_ID_MAX_LENGTH), nullable=True)
    first_seen_on: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_on: Mapped[date] = mapped_column(Date, nullable=False)
    vanished_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    excluded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    excluded_reasons: Mapped[str] = mapped_column(
        String(256), default="", server_default="", nullable=False
    )


class ReviewEvent(Base):
    """One change to an existing review, as of the walk that noticed it.

    Attributes:
        id: UUIDv7.
        workspace_id: Owning кабинет.
        observed_on: Moscow date of the walk.
        review_id / nm_id / imt_id: Which review, on which card.
        kind: A :class:`ReviewEventKind` value.
        old_valuation / new_valuation: The score before and after where that
            is the change; otherwise the score at the time, in ``old_valuation``.
        detail: The replacing review's id, or WB's exclusion reasons.
    """

    __tablename__ = "review_event"
    __table_args__ = (
        Index("ix_review_event_workspace_imt_day", "workspace_id", "imt_id", "observed_on"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workspace_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    observed_on: Mapped[date] = mapped_column(Date, nullable=False)
    review_id: Mapped[str] = mapped_column(String(REVIEW_ID_MAX_LENGTH), nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    imt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    old_valuation: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    new_valuation: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    detail: Mapped[str] = mapped_column(String(256), default="", server_default="", nullable=False)
