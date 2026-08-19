"""Per-day price/stock resolution and the ₽ values derived from them.

Everything here is a pure function over already-fetched snapshots: a day is
priced (or stocked) ONLY when a snapshot was captured on that exact date —
values are never carried onto days that were not observed.
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import PriceSnapshot
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import MatrixFunnelBase, MatrixStockBase


def ad_order_sum(orders: int, funnel: MatrixFunnelBase | None) -> float | None:
    """«Заказы, ₽» an advertising slice brought = its orders x the day's price.

    WB exposes no zone-attributed order revenue (and none at all for a split
    campaign), so the volume is DERIVED here — the same ``count x seller_price``
    rule the «Общая» column uses, applied to the ad slice.

    ``orders`` is the CAMPAIGN's count, all associated size/colour variants
    included (an ad bucket carries no other kind — see :class:`_AdSlice`),
    because the column measures a рекламная кампания: an order the campaign
    paid for is revenue it brought whichever variant the buyer finally picked.
    It is priced at the viewed card's ``seller_price`` — the only price a
    SKU-scoped view has, and an approximation whenever the variants are not
    priced alike.

    The funnel row itself is not required (ad orders are facts of the ad feed,
    not the funnel) — only the day's seller price. ``None`` when the day is
    unpriced.
    """
    if funnel is None or funnel.seller_price is None:
        return None
    return round(orders * funnel.seller_price, 2)


def ad_buyout_sum(
    orders: int, funnel: MatrixFunnelBase | None, lagged_buyout_percent: float | None
) -> float | None:
    """«Выкупы, ₽» an advertising slice brought = its «Заказы, ₽» x «Процент выкупа».

    Order-date attributed, exactly like the «Общая» column's buyout value: the
    orders a campaign delivered on day D are worth what that day's cohort
    actually bought out. ``None`` when the day is unpriced or the lagged buyout
    percent could not be computed.
    """
    order_sum = ad_order_sum(orders, funnel)
    if order_sum is None or lagged_buyout_percent is None:
        return None
    return round(order_sum * lagged_buyout_percent / 100, 2)


def price_for_day(ordered: list[PriceSnapshot], day: date) -> tuple[float | None, float | None]:
    """``(seller, customer)`` price for ``day`` — actual snapshots only.

    A day is priced ONLY when a snapshot was captured on that exact date;
    other days return ``(None, None)`` and render as «—». Snapshots are
    deliberately NOT carried onto neighbouring days: a price shown for a day
    we never observed would be fabricated data (and it silently skews the
    derived «Заказы/Выкупы, ₽»).

    Args:
        ordered: The SKU's price snapshots, ascending by date.
        day: The display day to price.

    Returns:
        The ``(seller_price, customer_price)`` for the day (either may be
        ``None`` when that side was not captured on the day's snapshot).
    """
    chosen = next((s for s in ordered if s.stat_date == day), None)
    if chosen is None:
        return None, None
    seller = float(chosen.seller_price) if chosen.seller_price is not None else None
    customer = float(chosen.customer_price) if chosen.customer_price is not None else None
    return seller, customer


def _stock_for_day(ordered: list[StockDailyTotal], day: date) -> MatrixStockBase | None:
    """Stock totals for ``day`` — actual snapshots only (same rule as prices).

    ``None`` (rendered «—») unless a stock snapshot was captured on that exact
    date; totals are never carried onto days we did not observe.

    Args:
        ordered: The SKU's per-day stock totals, ascending by date.
        day: The display day to resolve.

    Returns:
        The day's :class:`MatrixStockBase`, or ``None`` without a snapshot.
    """
    chosen = next((t for t in ordered if t.stat_date == day), None)
    if chosen is None:
        return None
    return MatrixStockBase(
        quantity=chosen.quantity,
        in_way_to_client=chosen.in_way_to_client,
        in_way_from_client=chosen.in_way_from_client,
    )


def _funnel_order_sum(funnel: MatrixFunnelBase | None) -> float | None:
    """«Заказы, ₽» = order_count x seller_price (``None`` when unpriced).

    ``None`` too on a price-only day (no funnel row yet): the zero count is
    not a fact, so ``0 x price = 0 ₽`` would be fabricated.
    """
    if funnel is None or not funnel.has_funnel or funnel.seller_price is None:
        return None
    return round(funnel.order_count * funnel.seller_price, 2)


def _buyout_sum(
    funnel: MatrixFunnelBase | None, lagged_buyout_percent: float | None
) -> float | None:
    """«Выкупы, ₽» = «Заказы, ₽» x «Процент выкупа» — the order-date buyout value.

    Attributed to the ORDER date (like «Заказы, ₽») so the row is congruent:
    ``order_count x seller_price x buyout% = «Заказы, ₽» x «Процент выкупа»``.
    ``None`` when the day is unpriced / has no funnel row, or the lagged buyout
    percent could not be computed.
    """
    order_sum = _funnel_order_sum(funnel)
    if order_sum is None or lagged_buyout_percent is None:
        return None
    return round(order_sum * lagged_buyout_percent / 100, 2)


def _funnel_spp(funnel: MatrixFunnelBase | None) -> float | None:
    """«СПП, %» = (seller - customer) / seller x 100 (``None`` when incomplete)."""
    if funnel is None or not funnel.seller_price or funnel.customer_price is None:
        return None
    return round((funnel.seller_price - funnel.customer_price) / funnel.seller_price * 100, 2)
