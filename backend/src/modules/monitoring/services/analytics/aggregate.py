"""Account-wide daily series for the «Сравнение SKU» page.

Sums the SKUs in scope day by day, then derives the ratios FROM THOSE SUMS.
That last part is the whole reason this lives on the server rather than being
three additions in the browser: a conversion rate is not additive, and the
average of per-SKU conversions is not the account's conversion. A card with 2
orders from 4 carts and one with 8 from 400 convert at 50% and 2%; the account
converted 10 of 404, which is 2.5% — not the 26% an average would print.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from src.modules.monitoring.repos import (
    AdvertisingRepository,
    FunnelRepository,
    StockRepository,
)
from src.modules.monitoring.repos.advertising import AdDayTotal
from src.modules.monitoring.repos.funnel import FunnelDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas import MetricWindow
from src.modules.monitoring.schemas.aggregate import AggregateChartsResponse
from src.modules.monitoring.schemas.matrix import MatrixMetricRow, MetricsMatrixRead
from src.modules.monitoring.services.analytics.window import resolve_window

#: The buckets this page populates. «Общая» is the account's whole day;
#: «Органика» is that day minus what advertising brought.
_BUCKETS: tuple[str, ...] = ("total", "organic")

#: Metric rows the page serves, in the order the charts read them.
_METRIC_KEYS: tuple[str, ...] = (
    "spend",
    "views",
    "clicks",
    "cpm",
    "carts",
    "cart_conversion",
    "orders",
    "order_conversion",
    "order_sum",
    "drr_orders",
    "stock_quantity",
    "stock_to_client",
    "stock_from_client",
    "stock_total",
)


def _percent(part: float | None, whole: float | None) -> float | None:
    """``part / whole`` as a percentage, or ``None`` when it cannot be one."""
    if part is None or not whole:
        return None
    return round(part / whole * 100, 2)


def _non_negative(value: int) -> int:
    """Clamp an «organic = funnel - ads» difference at zero.

    The two feeds are collected separately and attribute slightly differently,
    so on a heavily advertised day the ad counts can nose past the funnel's by a
    click or two. A negative «Органика» is never a fact about the day; it is
    that seam, and it renders as a line dipping below the axis.
    """
    return max(0, value)


class AggregateAnalytics:
    """Builds the account-wide day series the «Сравнение SKU» page draws."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        stock_repo: StockRepository,
    ) -> None:
        """Inject the three daily aggregators this composes."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._stock = stock_repo

    async def get_charts(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date | None,
        date_to: date | None,
        nm_ids: list[int] | None,
    ) -> AggregateChartsResponse:
        """Return the summed day series for the window and SKU selection.

        Args:
            workspace_id: The active workspace; SKUs outside it never surface.
            date_from: Inclusive start; defaults with :func:`resolve_window`.
            date_to: Inclusive end.
            nm_ids: The SKUs to include. ``None`` or empty means all of them —
                the page's default, and what «across all SKUs» means here.

        Returns:
            The window, the SKUs included, and a day x bucket matrix.
        """
        start, end = resolve_window(date_from, date_to)
        window = MetricWindow(start=start, end=end)
        selected = nm_ids or None

        funnel_days = await self._funnel.daily_totals(
            workspace_id=workspace_id,
            date_from=start,
            date_to=end,
            nm_ids=selected,
        )
        ad_days = await self._advertising.daily_totals(
            workspace_id=workspace_id,
            date_from=start,
            date_to=end,
            nm_ids=selected,
        )
        stock_days = await self._stock.daily_totals(
            workspace_id=workspace_id,
            date_from=start,
            date_to=end,
            nm_ids=selected,
        )

        # Every day of the window, present or not: a gap in the middle of a
        # series is a day nobody reported, and the chart must be able to show
        # it as a gap rather than closing over it.
        days = _window_days(start, end)
        funnel_by_day = {row.stat_date: row for row in funnel_days}
        ad_by_day = {row.stat_date: row for row in ad_days}
        stock_by_day = {row.stat_date: row for row in stock_days}

        cells: dict[str, list[float | None]] = {key: [] for key in _METRIC_KEYS}
        for day in days:
            funnel = funnel_by_day.get(day)
            ad = ad_by_day.get(day)
            stock = stock_by_day.get(day)
            for key in _METRIC_KEYS:
                total, organic = _cell(key, funnel, ad, stock)
                cells[key].extend((total, organic))

        return AggregateChartsResponse(
            window=window,
            nm_ids=sorted(selected) if selected else [],
            sku_count=max((row.sku_count for row in funnel_days), default=0),
            matrix=MetricsMatrixRead(
                days=days,
                buckets=list(_BUCKETS),
                rows=[MatrixMetricRow(key=key, values=cells[key]) for key in _METRIC_KEYS],
            ),
        )


def _window_days(start: date, end: date) -> list[date]:
    """Every date in the inclusive window, ascending."""
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _cell(
    key: str,
    funnel: FunnelDayTotal | None,
    ad: AdDayTotal | None,
    stock: StockDailyTotal | None,
) -> tuple[float | None, float | None]:
    """Return one metric's ``(«Общая», «Органика»)`` pair for a day.

    «Органика» is defined only for the three funnel counts — the day's own
    traffic minus what advertising delivered. Money and stock have no organic
    half: an unadvertised card still costs nothing and holds the same units.

    A ``None`` means «nobody reported this», and stays ``None`` rather than
    becoming a zero, so a gap in the harvest draws as a gap.
    """
    ad_clicks = ad.clicks if ad else 0
    ad_carts = ad.add_to_cart if ad else 0
    ad_orders = ad.orders if ad else 0

    match key:
        case "spend":
            return (None if ad is None else round(ad.spend, 2)), None
        case "views":
            return (None if ad is None else float(ad.views)), None
        case "clicks":
            if funnel is None:
                return None, None
            return float(funnel.open_count), float(_non_negative(funnel.open_count - ad_clicks))
        case "cpm":
            # Both halves come from the same advertising totals «Затраты» and
            # «Показы» are already served from, so this is the account's real
            # cost per thousand показов — not an average of per-card CPMs, which
            # would weight a card with 40 показов like one with 40 000.
            #
            # CTR has no counterpart here and stays absent: «Клики» on this page
            # is the funnel's card opens, not advertising clicks.
            if ad is None or not ad.views:
                return None, None
            return round(ad.spend / ad.views * 1000, 2), None
        case "carts":
            if funnel is None:
                return None, None
            return float(funnel.cart_count), float(_non_negative(funnel.cart_count - ad_carts))
        case "orders":
            if funnel is None:
                return None, None
            return float(funnel.order_count), float(_non_negative(funnel.order_count - ad_orders))
        case "cart_conversion":
            if funnel is None:
                return None, None
            return _percent(funnel.cart_count, funnel.open_count), None
        case "order_conversion":
            if funnel is None:
                return None, None
            return _percent(funnel.order_count, funnel.cart_count), None
        case "order_sum":
            return (None if funnel is None else funnel.order_sum), None
        case "drr_orders":
            if ad is None or funnel is None:
                return None, None
            return _percent(ad.spend, funnel.order_sum), None
        case "stock_quantity":
            return (None if stock is None else float(stock.quantity)), None
        case "stock_to_client":
            return (None if stock is None else float(stock.in_way_to_client)), None
        case "stock_from_client":
            return (None if stock is None else float(stock.in_way_from_client)), None
        case "stock_total":
            if stock is None:
                return None, None
            held = stock.quantity + stock.in_way_to_client + stock.in_way_from_client
            return float(held), None
        case _:
            return None, None
