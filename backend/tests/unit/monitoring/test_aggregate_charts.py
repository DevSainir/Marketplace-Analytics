"""The account-wide «Графики» series: what may be summed, and what may not.

The point of these is the arithmetic, not the plumbing. Summing counts across
SKUs is trivial; the two things that are easy to get wrong — and expensive,
because the result still looks like a number — are recomputing ratios from the
sums instead of averaging per-SKU ratios, and letting a two-feed seam print a
negative «Органика».
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from src.modules.monitoring.repos.advertising import AdDayTotal
from src.modules.monitoring.repos.funnel import FunnelDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.services.analytics.aggregate import AggregateAnalytics

WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
DAY = date(2026, 8, 10)
NEXT = date(2026, 8, 11)


class _FakeDailyRepo:
    """A repo that replays the rows it was built with, whatever is asked."""

    def __init__(self, rows: list[object]) -> None:
        self.rows = rows
        self.nm_ids: list[int] | None = None

    async def daily_totals(self, **kwargs: object) -> list[object]:
        """Record the SKU filter and replay the rows."""
        self.nm_ids = kwargs.get("nm_ids")  # type: ignore[assignment]
        return self.rows


def _service(
    *,
    funnel: list[FunnelDayTotal] | None = None,
    ads: list[AdDayTotal] | None = None,
    stock: list[StockDailyTotal] | None = None,
) -> tuple[AggregateAnalytics, _FakeDailyRepo]:
    """Build the service over fake daily repos, returning the funnel fake too."""
    funnel_repo = _FakeDailyRepo(funnel or [])
    return (
        AggregateAnalytics(
            funnel_repo=funnel_repo,  # type: ignore[arg-type]
            advertising_repo=_FakeDailyRepo(ads or []),  # type: ignore[arg-type]
            stock_repo=_FakeDailyRepo(stock or []),  # type: ignore[arg-type]
        ),
        funnel_repo,
    )


def _cell(response: object, key: str, bucket: str, day_index: int = 0) -> float | None:
    """Read one cell out of the day-major matrix."""
    matrix = response.matrix  # type: ignore[attr-defined]
    row = next(r for r in matrix.rows if r.key == key)
    return row.values[day_index * len(matrix.buckets) + matrix.buckets.index(bucket)]


async def test_conversion_is_recomputed_from_the_sums_not_averaged() -> None:
    """The account's conversion, not the mean of its cards' conversions.

    A card converting 2 of 4 and one converting 8 of 400 do not make an account
    that converts 26%: 10 of 404 is 2.5%. Averaging ratios is the single most
    expensive mistake available here, because the answer stays plausible.
    """
    service, _ = _service(
        funnel=[
            FunnelDayTotal(
                stat_date=DAY,
                sku_count=2,
                open_count=1000,
                cart_count=404,
                order_count=10,
                buyout_count=8,
                order_sum=5000.0,
            )
        ]
    )

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=DAY, nm_ids=None
    )

    assert _cell(result, "order_conversion", "total") == pytest.approx(2.48, abs=0.01)
    assert _cell(result, "cart_conversion", "total") == pytest.approx(40.4, abs=0.01)


async def test_organic_is_the_day_minus_advertising() -> None:
    """«Органика» is what the funnel did beyond what the ads delivered."""
    service, _ = _service(
        funnel=[
            FunnelDayTotal(
                stat_date=DAY,
                sku_count=1,
                open_count=500,
                cart_count=100,
                order_count=40,
                buyout_count=30,
                order_sum=1000.0,
            )
        ],
        ads=[
            AdDayTotal(stat_date=DAY, views=9000, clicks=200, add_to_cart=30, orders=12, spend=50.0)
        ],
    )

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=DAY, nm_ids=None
    )

    assert _cell(result, "orders", "total") == 40
    assert _cell(result, "orders", "organic") == 28
    assert _cell(result, "clicks", "organic") == 300


async def test_a_seam_between_the_two_feeds_never_prints_negative_organic() -> None:
    """Ad counts can nose past the funnel's; a negative organic is not a fact.

    The funnel and the advertising feed are collected separately and attribute
    slightly differently, so on a heavily advertised day the ads can claim one
    order more than the funnel recorded. That is the seam, not a day on which
    the account un-sold something.
    """
    service, _ = _service(
        funnel=[
            FunnelDayTotal(
                stat_date=DAY,
                sku_count=1,
                open_count=10,
                cart_count=5,
                order_count=2,
                buyout_count=1,
                order_sum=100.0,
            )
        ],
        ads=[AdDayTotal(stat_date=DAY, views=99, clicks=40, add_to_cart=9, orders=5, spend=10.0)],
    )

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=DAY, nm_ids=None
    )

    assert _cell(result, "orders", "organic") == 0
    assert _cell(result, "clicks", "organic") == 0


async def test_a_day_nobody_reported_stays_blank_rather_than_zero() -> None:
    """A gap in the harvest is not a day of zero orders.

    Every day of the window is present so the chart can draw the gap; the cells
    are `None`, which renders as a break in the line rather than a dive to the
    axis.
    """
    service, _ = _service(
        funnel=[
            FunnelDayTotal(
                stat_date=NEXT,
                sku_count=1,
                open_count=10,
                cart_count=5,
                order_count=2,
                buyout_count=1,
                order_sum=100.0,
            )
        ]
    )

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=NEXT, nm_ids=None
    )

    assert result.matrix.days == [DAY, NEXT]
    assert _cell(result, "orders", "total", day_index=0) is None
    assert _cell(result, "orders", "total", day_index=1) == 2


async def test_drr_is_spend_over_the_days_own_revenue() -> None:
    """ДРР needs both halves; an unpriced day has no denominator to divide by."""
    service, _ = _service(
        funnel=[
            FunnelDayTotal(
                stat_date=DAY,
                sku_count=1,
                open_count=10,
                cart_count=5,
                order_count=2,
                buyout_count=1,
                order_sum=1000.0,
            ),
            FunnelDayTotal(
                stat_date=NEXT,
                sku_count=1,
                open_count=10,
                cart_count=5,
                order_count=2,
                buyout_count=1,
                order_sum=None,
            ),
        ],
        ads=[
            AdDayTotal(stat_date=DAY, views=1, clicks=1, add_to_cart=0, orders=0, spend=120.0),
            AdDayTotal(stat_date=NEXT, views=1, clicks=1, add_to_cart=0, orders=0, spend=120.0),
        ],
    )

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=NEXT, nm_ids=None
    )

    assert _cell(result, "drr_orders", "total", day_index=0) == pytest.approx(12.0)
    assert _cell(result, "drr_orders", "total", day_index=1) is None


async def test_an_empty_selection_means_every_sku_not_none_of_them() -> None:
    """The page opens on the whole account; the picker narrows from there."""
    service, funnel_repo = _service()

    result = await service.get_charts(workspace_id=WORKSPACE, date_from=DAY, date_to=DAY, nm_ids=[])

    assert funnel_repo.nm_ids is None
    assert result.nm_ids == []


async def test_a_selection_is_passed_down_and_reported_back() -> None:
    """The response names the SKUs it covered, so a stale picker cannot lie."""
    service, funnel_repo = _service()

    result = await service.get_charts(
        workspace_id=WORKSPACE, date_from=DAY, date_to=DAY, nm_ids=[7, 3]
    )

    assert funnel_repo.nm_ids == [7, 3]
    assert result.nm_ids == [3, 7]
