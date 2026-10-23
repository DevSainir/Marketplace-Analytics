"""The review history against a real database: two days, and what the second records.

What only Postgres can show: that a review missing from a complete walk is
marked vanished on that day and nobody else's is, that a walk which did not
finish declares nothing, that the overlap between pages saves the review that
slides across a page boundary when another one is answered mid-walk, and that a
day's rating snapshot is written once. WB is faked; its shapes are the ones
pinned by the client tests.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients import FeedbackPage
from src.integrations.wildberries.schemas import WBFeedback, WBStorefrontRating
from src.modules.monitoring.models import RatingSnapshot, ReviewEvent, ReviewState
from src.modules.monitoring.repos import ReviewRepository
from src.modules.monitoring.services.reviews import HistoryResult, ReviewHistory

WORKSPACE = uuid.uuid4()
NEIGHBOUR = uuid.uuid4()
DAY_1 = date(2026, 10, 1)
DAY_2 = DAY_1 + timedelta(days=1)
IMT = 7001


def review(review_id: str, valuation: int = 5, *, child: str | None = None) -> WBFeedback:
    return WBFeedback.model_validate(
        {
            "id": review_id,
            "productValuation": valuation,
            "createdDate": "2026-09-01T10:00:00Z",
            "childFeedbackId": child,
            "productDetails": {"nmId": 953770957, "imtId": IMT},
        }
    )


class FakeReviewList:
    """Both halves of WB's review list, served by offset like WB serves them."""

    def __init__(
        self,
        unanswered: list[WBFeedback],
        answered: list[WBFeedback] | None = None,
        *,
        on_page: Callable[[FakeReviewList], None] | None = None,
        fail_answered: bool = False,
    ) -> None:
        self.halves = {False: list(unanswered), True: list(answered or [])}
        self._on_page = on_page
        self._fail_answered = fail_answered

    async def fetch_page(self, *, answered: bool, take: int, skip: int) -> FeedbackPage:
        if answered and self._fail_answered:
            raise IntegrationError("WildBerries API error 500 on /api/v1/feedbacks.")
        items = self.halves[answered][skip : skip + take]
        if self._on_page is not None:
            self._on_page(self)
            self._on_page = None
        return FeedbackPage(items=items, received=len(items), malformed=0)


class FakeStorefront:
    """The storefront summary per merged-card group, or the refusal it answers with."""

    def __init__(self, answers: dict[int, Any] | None = None) -> None:
        self.answers = answers or {}
        self.asked: list[int] = []

    async def fetch_rating(self, imt_id: int) -> WBStorefrontRating | None:
        self.asked.append(imt_id)
        answer = self.answers.get(imt_id)
        if isinstance(answer, Exception):
            raise answer
        return answer


def rating(**fields: Any) -> WBStorefrontRating:
    base = {"valuation": "4.7", "valuationSum": 4136, "feedbackCount": 880}
    return WBStorefrontRating.model_validate(base | fields)


async def run(
    session: AsyncSession,
    reviews: FakeReviewList,
    *,
    today: date,
    storefront: FakeStorefront | None = None,
    workspace_id: uuid.UUID = WORKSPACE,
) -> HistoryResult:
    return await ReviewHistory(
        ReviewRepository(session),
        commit=session.commit,
        feedbacks=reviews,
        storefront=storefront or FakeStorefront(),
        workspace_id=workspace_id,
        today=today,
    ).run()


async def events(session: AsyncSession) -> list[tuple[str, str, date]]:
    rows = await session.execute(
        sa.select(ReviewEvent.review_id, ReviewEvent.kind, ReviewEvent.observed_on)
        .where(ReviewEvent.workspace_id == WORKSPACE)
        .order_by(ReviewEvent.review_id, ReviewEvent.kind)
    )
    return [tuple(row) for row in rows.all()]  # type: ignore[misc]


async def vanished(session: AsyncSession, workspace_id: uuid.UUID) -> dict[str, date | None]:
    rows = await session.execute(
        sa.select(ReviewState.review_id, ReviewState.vanished_on).where(
            ReviewState.workspace_id == workspace_id
        )
    )
    return dict(rows.all())  # type: ignore[arg-type]


async def test_a_review_missing_from_a_complete_walk_vanished_that_day(
    db_session: AsyncSession,
) -> None:
    """The 2026-10-02 question, answered: which reviews left the count, and when."""
    await run(db_session, FakeReviewList([review("a"), review("b", 1)], [review("c")]), today=DAY_1)
    await run(
        db_session,
        FakeReviewList([review("x")], [review("x")]),
        today=DAY_1,
        workspace_id=NEIGHBOUR,
    )

    result = await run(db_session, FakeReviewList([review("a")], [review("c")]), today=DAY_2)

    assert result.vanished == 1
    assert await events(db_session) == [("b", "vanished", DAY_2)]
    assert await vanished(db_session, WORKSPACE) == {"a": None, "b": DAY_2, "c": None}
    # The neighbour was not walked today; nothing of theirs is touched.
    assert await vanished(db_session, NEIGHBOUR) == {"x": None}


async def test_a_walk_that_did_not_finish_declares_nothing_vanished(
    db_session: AsyncSession,
) -> None:
    """An item "not listed" only means "gone" when every page was read."""
    await run(db_session, FakeReviewList([review("a")], [review("c")]), today=DAY_1)

    result = await run(db_session, FakeReviewList([review("a")], fail_answered=True), today=DAY_2)

    assert result.complete is False
    assert await vanished(db_session, WORKSPACE) == {"a": None, "c": None}


async def test_a_mass_disappearance_is_not_recorded(db_session: AsyncSession) -> None:
    """An empty answer from WB is a truncated list, not a workspace wiped by moderation."""
    await run(db_session, FakeReviewList([review(f"r{n}") for n in range(60)]), today=DAY_1)

    result = await run(db_session, FakeReviewList([]), today=DAY_2)

    assert result.vanish_refused == 60
    assert set((await vanished(db_session, WORKSPACE)).values()) == {None}


async def test_a_rescore_a_replacement_and_a_return_are_dated_to_the_walk(
    db_session: AsyncSession,
) -> None:
    await run(
        db_session, FakeReviewList([review("a", 1), review("b", 2), review("c")]), today=DAY_1
    )
    await run(db_session, FakeReviewList([review("a", 1), review("b", 2)]), today=DAY_2)

    await run(
        db_session,
        FakeReviewList([review("a", 4), review("b", 2, child="b2"), review("c")]),
        today=DAY_2 + timedelta(days=1),
    )

    day_3 = DAY_2 + timedelta(days=1)
    assert await events(db_session) == [
        ("a", "rescored", day_3),
        ("b", "replaced", day_3),
        ("c", "returned", day_3),
        ("c", "vanished", DAY_2),
    ]


async def test_overlapping_pages_keep_a_review_answered_mid_walk(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answering one review shifts every later offset back by one.

    Without the overlap the review that slid across the page boundary is never
    read, and the next walk reports it vanished — on a day nothing happened.
    """
    monkeypatch.setattr("src.modules.monitoring.services.reviews.history.PAGE_SIZE", 3)
    monkeypatch.setattr("src.modules.monitoring.services.reviews.history.PAGE_OVERLAP", 1)
    unanswered = [review(f"u{n}") for n in range(7)]
    await run(db_session, FakeReviewList(unanswered), today=DAY_1)

    def answer_the_first(fake: FakeReviewList) -> None:
        fake.halves[True].append(fake.halves[False].pop(0))

    result = await run(
        db_session, FakeReviewList(unanswered, on_page=answer_the_first), today=DAY_2
    )

    assert result.vanished == 0
    assert set((await vanished(db_session, WORKSPACE)).values()) == {None}


async def test_one_rating_snapshot_a_day_beside_our_own_count(db_session: AsyncSession) -> None:
    """The first read of the day stands; our count shows when the two lists part."""
    reviews = FakeReviewList([review("a"), review("b", 1, child="b2")])
    await run(db_session, reviews, today=DAY_1, storefront=FakeStorefront({IMT: rating()}))

    await run(
        db_session,
        reviews,
        today=DAY_1,
        storefront=FakeStorefront({IMT: rating(valuation="4.6")}),
    )

    rows = (await db_session.execute(sa.select(RatingSnapshot))).scalars().all()
    assert [(r.imt_id, str(r.valuation), r.seller_api_count) for r in rows] == [(IMT, "4.7", 1)]


async def test_an_exclusion_after_the_first_read_is_an_event(db_session: AsyncSession) -> None:
    """WB moderation moves the rating without deleting the review."""
    reviews = FakeReviewList([review("a", 1)])
    included = rating(feedbacks=[{"id": "a", "excludedFromRating": {"isExcluded": False}}])
    excluded = rating(
        feedbacks=[
            {"id": "a", "excludedFromRating": {"isExcluded": True, "reasons": ["notProduct"]}}
        ]
    )
    await run(db_session, reviews, today=DAY_1, storefront=FakeStorefront({IMT: included}))

    await run(db_session, reviews, today=DAY_2, storefront=FakeStorefront({IMT: excluded}))

    assert await events(db_session) == [("a", "excluded", DAY_2)]


async def test_the_storefront_is_left_alone_after_three_refusals(
    db_session: AsyncSession,
) -> None:
    """Asking on is how an unauthenticated reader gets its address blocked."""
    many = [
        WBFeedback.model_validate(
            {
                "id": f"r{n}",
                "productValuation": 5,
                "createdDate": "2026-09-01T10:00:00Z",
                "productDetails": {"nmId": 1000 + n, "imtId": 9000 + n},
            }
        )
        for n in range(6)
    ]
    refusing = FakeStorefront({9000 + n: IntegrationError("498") for n in range(6)})

    result = await run(db_session, FakeReviewList(many), today=DAY_1, storefront=refusing)

    assert refusing.asked == [9000, 9001, 9002]
    assert result.storefront_failures == 3
