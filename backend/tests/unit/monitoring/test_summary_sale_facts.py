"""Unit tests for the summary listing's sale-date facts.

Pins the rule that the listing reports sale-date COUNTS and exposes no
buyout ratio: "Buyout rate" divides by decided deliveries (buyouts +
refusals at pickup), and a refusal never becomes a sale record, so no ratio
built from this feed can answer it.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from src.modules.monitoring.repos.funnel import FunnelAggregate
from src.modules.monitoring.repos.sales import SaleWindowTotal
from src.modules.monitoring.services.analytics import AnalyticsService

NM_ID = 953770957
WORKSPACE_ID = uuid.uuid4()


class _FunnelRepo:
    """Serves one SKU's order-date funnel window totals."""

    async def aggregate_window(self, **_: Any) -> list[FunnelAggregate]:
        return [
            FunnelAggregate(
                nm_id=NM_ID,
                days_count=9,
                open_count=1000,
                cart_count=200,
                order_count=100,
                buyout_count=30,
                add_to_wishlist=5,
            )
        ]


class _SaleRepo:
    """Serves the SKU's sale-date settled records."""

    def __init__(self, buyouts: int, returns: int) -> None:
        self._totals = SaleWindowTotal(
            buyout_count=buyouts, buyout_sum=1000.0, return_count=returns
        )

    async def window_totals_by_sku(self, **_: Any) -> dict[int, SaleWindowTotal]:
        return {NM_ID: self._totals}


class _Empty:
    """Every other repo the summary composes over — all empty."""

    async def aggregate_window(self, **_: Any) -> list[Any]:
        return []

    async def latest_totals_by_sku(self, **_: Any) -> dict[int, int]:
        return {}

    async def latest_by_sku(self, **_: Any) -> dict[int, tuple[float | None, float | None]]:
        return {}

    async def get_by_ids(self, _ids: list[int]) -> dict[int, Any]:
        return {}


def _service(*, buyouts: int, returns: int) -> AnalyticsService:
    """Build an AnalyticsService with only the repos get_summary touches."""
    empty = _Empty()
    return AnalyticsService(
        funnel_repo=_FunnelRepo(),  # type: ignore[arg-type]
        advertising_repo=empty,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        advertising_write_off_repo=None,  # type: ignore[arg-type]
        stock_repo=empty,  # type: ignore[arg-type]
        campaign_repo=None,  # type: ignore[arg-type]
        product_card_repo=empty,  # type: ignore[arg-type]
        product_size_repo=None,  # type: ignore[arg-type]
        matrix_override_repo=None,  # type: ignore[arg-type]
        price_repo=empty,  # type: ignore[arg-type]
        sale_repo=_SaleRepo(buyouts, returns),  # type: ignore[arg-type]
        pinned_sku_repo=None,  # type: ignore[arg-type]
        day_comment_repo=None,  # type: ignore[arg-type]
        day_action_repo=None,  # type: ignore[arg-type]
    )


async def _item(*, buyouts: int, returns: int) -> Any:
    response = await _service(buyouts=buyouts, returns=returns).get_summary(
        workspace_id=WORKSPACE_ID, date_from=date(2026, 6, 30), date_to=date(2026, 7, 8)
    )
    return response.items[0]


async def test_sale_date_buyouts_and_returns_are_reported_as_counts() -> None:
    """Both sides of the sale-date feed surface as raw counts.

    Sample figures for one SKU-day: 274 buyouts, 30 returns.
    """
    item = await _item(buyouts=274, returns=30)

    assert item.total_buyout_count == 274
    assert item.total_return_count == 30


async def test_summary_exposes_no_buyout_ratio() -> None:
    """The listing must not serve a "Buyout rate"-shaped number.

    Regression: `buyout_conversion = buyouts / (buyouts + returns)` read 90.13%
    for this SKU while WB's "Buyout rate" was ~30%, because a refusal at
    pickup never becomes a sale record and so is invisible to this feed. The
    ratio was removed rather than corrected — it cannot be computed here (the
    cohort's `cancel_count` only covers 22 days, this window allows 366), and
    "Buyout rate" lives on the matrix. Callers wanting a return rate can
    divide the two counts themselves.
    """
    item = await _item(buyouts=274, returns=30)

    assert not hasattr(item, "buyout_conversion")
    assert not hasattr(item, "return_rate")


async def test_sale_counts_are_zero_without_records() -> None:
    """No sale records in the window -> plain zeros."""
    item = await _item(buyouts=0, returns=0)

    assert item.total_buyout_count == 0
    assert item.total_return_count == 0
