"""The rating read off the funnel aggregate: what WB's numbers become.

``0`` is WB's value for a card with no reviews; stored as a zero-star rating it
would render «0 ★» on a card nobody has rated. The response can also carry more
decimals than the storefront shows, and the header prints one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, cast

from src.integrations.wildberries.schemas import WBFunnelAggregateRow
from src.modules.monitoring.services.ingestion.service import IngestionService

WORKSPACE = uuid.uuid4()


class FakeProductCards:
    """Records the one write the rating ingestion makes."""

    def __init__(self) -> None:
        self.written: dict[int, Decimal | None] = {}
        self.workspace_id: uuid.UUID | None = None

    async def set_feedback_ratings(
        self, ratings: dict[int, Decimal | None], *, workspace_id: uuid.UUID
    ) -> int:
        self.written = ratings
        self.workspace_id = workspace_id
        return len(ratings)


def _row(nm_id: int, rating: float) -> WBFunnelAggregateRow:
    empty = {"openCount": 0, "cartCount": 0, "orderCount": 0}
    return WBFunnelAggregateRow.model_validate(
        {
            "product": {"nmId": nm_id, "feedbackRating": rating, "productRating": 10},
            "statistic": {"selected": empty, "past": empty, "comparison": {}},
        }
    )


def _service(cards: FakeProductCards) -> IngestionService:
    unused = cast(Any, object())
    return IngestionService(
        funnel_repo=unused,
        advertising_repo=unused,
        stock_repo=unused,
        campaign_repo=unused,
        product_card_repo=cast(Any, cards),
        product_size_repo=unused,
        advertising_search_repo=unused,
        advertising_cluster_repo=unused,
        advertising_write_off_repo=unused,
        price_repo=unused,
        sale_repo=unused,
    )


async def test_ratings_are_stored_to_one_decimal_and_no_reviews_as_unknown() -> None:
    cards = FakeProductCards()

    await _service(cards).ingest_feedback_ratings(
        [_row(953770957, 4.7), _row(995716075, 4.84), _row(1944299862, 0)],
        workspace_id=WORKSPACE,
    )

    assert cards.written == {
        953770957: Decimal("4.7"),
        995716075: Decimal("4.8"),
        1944299862: None,
    }
    assert cards.workspace_id == WORKSPACE
