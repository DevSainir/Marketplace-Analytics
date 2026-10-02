"""Per-day price/stock resolution and the order money derived from them.

Everything here is a pure function over already-fetched snapshots: a day is
priced (or stocked) ONLY when a snapshot was captured on that exact date —
values are never carried onto days that were not observed.

Order money is valued at :func:`order_unit` — WB's own funnel sum per order
where WB served one, the seller price otherwise — and is in that unit's
currency, which is not always the prices' (see :class:`MatrixFunnelBase`).
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import PriceSnapshot
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import MatrixFunnelBase, MatrixStockBase


def order_unit(funnel: MatrixFunnelBase | None) -> tuple[float | None, str]:
    """What one order is worth that day, and the currency it is counted in.

    WB's funnel sum per order (``order_price``) where WB served one — the
    settlement currency, converted by WB at the order day's rate — otherwise
    the seller price converted at that same Bank rate (``price_rate``), or
    without one the seller price in the prices' currency. Every order-money cell of the day
    is valued at this one unit, so a day's order money is in one currency.
    """
    if funnel is None:
        return None, ""
    if funnel.order_price is not None and funnel.order_currency:
        return funnel.order_price, funnel.order_currency
    if funnel.seller_price is not None and funnel.price_rate is not None and funnel.order_currency:
        return round(funnel.seller_price * funnel.price_rate, 2), funnel.order_currency
    return funnel.seller_price, funnel.price_currency


def ad_order_sum(orders: int, funnel: MatrixFunnelBase | None) -> float | None:
    """«Заказы» an advertising slice brought = its orders x the day's order unit.

    WB exposes no zone-attributed order revenue (and none at all for a split
    campaign), so the volume is DERIVED here — the same ``count x unit`` rule
    the «Общая» column uses, applied to the ad slice (see :func:`order_unit`).

    ``orders`` is the CAMPAIGN's count, all associated size/colour variants
    included (an ad bucket carries no other kind — see :class:`_AdSlice`),
    because the column measures a рекламная кампания: an order the campaign
    paid for is revenue it brought whichever variant the buyer finally picked.
    It is valued at the viewed card's order unit — the only price a SKU-scoped
    view has, and an approximation whenever the variants are not priced alike.

    The funnel counts themselves are not required (ad orders are facts of the
    ad feed, not the funnel) — only the day's unit. ``None`` when the day is
    unpriced.
    """
    price, _currency = order_unit(funnel)
    if price is None:
        return None
    return round(orders * price, 2)


def ad_buyout_sum(
    orders: int, funnel: MatrixFunnelBase | None, lagged_buyout_percent: float | None
) -> float | None:
    """«Выкупы» an advertising slice brought = its «Заказы» x «Процент выкупа».

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
    """«Заказы» = order_count x the day's order unit (``None`` when unpriced).

    With WB's funnel sum this IS that sum — ``count x sum / count`` — and it
    still follows an edited count. ``None`` on a price-only day (no funnel row
    yet): the zero count is not a fact, so ``0 x price = 0`` would be fabricated.
    """
    if funnel is None or not funnel.has_funnel:
        return None
    price, _currency = order_unit(funnel)
    if price is None:
        return None
    return round(funnel.order_count * price, 2)


def _buyout_sum(
    funnel: MatrixFunnelBase | None, lagged_buyout_percent: float | None
) -> float | None:
    """«Выкупы» = «Заказы» x «Процент выкупа» — the order-date buyout value.

    Attributed to the ORDER date (like «Заказы») so the row is congruent:
    ``order_count x unit x buyout% = «Заказы» x «Процент выкупа»``.
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
