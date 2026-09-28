"""What a heatmap cell holds, how cells combine, and how a metric is read off one.

A cell is not a number. It is the ADDITIVE facts behind every metric — orders,
opens, spend, revenue… — and a metric is derived from them only at the end.
That is the whole trick of the «Итого» row and column: a CTR over a week is
Σ clicks / Σ views, never the average of seven CTRs, and a category's ДРР is its
summed spend over its summed orders. Summing ratios is how a heatmap's totals
come out plausible and wrong.

Two things do not add up, and each has its own rule:

* **Stock is a level, not a flow.** Across days it is the LATEST snapshot (the
  stock «за неделю» is what was on the shelf at the end of it); across articles
  it is the sum. :func:`merge_days` and :func:`merge_skus` are therefore two
  functions, not one.
* **Money from the settlement is unknown until WB calculates it.** A day after
  the last settled one is ``None``, not zero — zero would read as a collapse in
  sales. A cell is «known» for finance as soon as one of its days is settled,
  and advertising is subtracted from profit only for those days, or a
  half-settled week would carry its whole ad spend against half its revenue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal

_ZERO = Decimal(0)

#: Which loaded source each metric reads. The loader fetches only what the
#: chosen metrics need — stock is a row per warehouse per size per day, and a
#: view of orders must not pay for it.
METRIC_SOURCES: dict[str, frozenset[str]] = {
    "orders": frozenset({"funnel"}),
    "order_sum": frozenset({"funnel"}),
    "opens": frozenset({"funnel"}),
    "carts": frozenset({"funnel"}),
    "cart_conversion": frozenset({"funnel"}),
    "order_conversion": frozenset({"funnel"}),
    "organic_opens": frozenset({"funnel", "ads"}),
    "spend": frozenset({"funnel", "ads"}),
    "ad_views": frozenset({"funnel", "ads"}),
    "ad_clicks": frozenset({"funnel", "ads"}),
    "ctr": frozenset({"funnel", "ads"}),
    "cpc": frozenset({"funnel", "ads"}),
    "cpm": frozenset({"funnel", "ads"}),
    "ad_orders": frozenset({"funnel", "ads"}),
    "ad_cr": frozenset({"funnel", "ads"}),
    "cpo": frozenset({"funnel", "ads"}),
    "drr_orders": frozenset({"funnel", "ads"}),
    "seller_price": frozenset({"funnel", "prices"}),
    "customer_price": frozenset({"funnel", "prices"}),
    "spp": frozenset({"funnel", "prices"}),
    "stock": frozenset({"stock"}),
    "revenue": frozenset({"finance"}),
    "sales": frozenset({"finance"}),
    "profit": frozenset({"finance", "ads"}),
    "margin": frozenset({"finance", "ads"}),
}


@dataclass(slots=True)
class Facts:
    """The additive facts of one cell — a SKU-day, or any sum of them.

    Every ``*_days`` counter says a source reported for at least one day of the
    cell, which is what separates «0» from «we were not told».
    """

    funnel_days: int = 0
    opens: int = 0
    carts: int = 0
    orders: int = 0
    #: Orders on days that carried a seller price, and what they were worth.
    priced_orders: int = 0
    amount_seller: Decimal = _ZERO
    #: The same for the price after WB's СПП.
    paid_orders: int = 0
    amount_paid: Decimal = _ZERO

    ad_days: int = 0
    spend: Decimal = _ZERO
    ad_views: int = 0
    ad_clicks: int = 0
    ad_orders: int = 0

    #: Price snapshots, for a cell with no orders to weight them by.
    seller_price_sum: Decimal = _ZERO
    seller_price_n: int = 0
    customer_price_sum: Decimal = _ZERO
    customer_price_n: int = 0

    #: Units on the shelf on :attr:`stock_date`; see the module docstring.
    stock: int | None = None
    stock_date: date | None = None

    #: At least one day of the cell is settled.
    finance_known: bool = False
    revenue: Decimal = _ZERO
    sold_units: int = 0
    payout_net: Decimal = _ZERO
    cogs: Decimal = _ZERO
    #: Some article in the cell moved units with no cost price on file.
    uncosted: bool = False
    #: Advertising on the SETTLED days only — what profit subtracts.
    settled_spend: Decimal = _ZERO


#: Fields that are neither plain sums nor the stock pair.
_SPECIAL = frozenset({"stock", "stock_date", "finance_known", "uncosted"})
#: Every plain sum — what :func:`_add_flows` must add. Kept as a derived list so
#: a test can prove the hand-written additions below miss none of them.
ADDITIVE_FIELDS = tuple(f.name for f in fields(Facts) if f.name not in _SPECIAL)


def _add_flows(target: Facts, other: Facts) -> None:
    """Add every additive field and OR the two flags.

    Written out field by field rather than looped over :data:`ADDITIVE_FIELDS`
    with ``getattr``/``setattr``: this runs once per SKU-day per fold, and on
    production the loop was most of a grid's time — 335 000 attribute calls for
    one кабинет's month. The unit tier pins that no field is left out.
    """
    target.funnel_days += other.funnel_days
    target.opens += other.opens
    target.carts += other.carts
    target.orders += other.orders
    target.priced_orders += other.priced_orders
    target.amount_seller += other.amount_seller
    target.paid_orders += other.paid_orders
    target.amount_paid += other.amount_paid
    target.ad_days += other.ad_days
    target.spend += other.spend
    target.ad_views += other.ad_views
    target.ad_clicks += other.ad_clicks
    target.ad_orders += other.ad_orders
    target.seller_price_sum += other.seller_price_sum
    target.seller_price_n += other.seller_price_n
    target.customer_price_sum += other.customer_price_sum
    target.customer_price_n += other.customer_price_n
    target.revenue += other.revenue
    target.sold_units += other.sold_units
    target.payout_net += other.payout_net
    target.cogs += other.cogs
    target.settled_spend += other.settled_spend
    target.finance_known = target.finance_known or other.finance_known
    target.uncosted = target.uncosted or other.uncosted


def merge_days(target: Facts, other: Facts) -> None:
    """Fold another stretch of the SAME articles into ``target`` — stock stays the latest."""
    _add_flows(target, other)
    if other.stock_date is not None and (
        target.stock_date is None or other.stock_date >= target.stock_date
    ):
        target.stock = other.stock
        target.stock_date = other.stock_date


def merge_skus(target: Facts, other: Facts) -> None:
    """Fold OTHER articles over the same stretch into ``target`` — stock adds up."""
    _add_flows(target, other)
    if other.stock is not None:
        target.stock = (target.stock or 0) + other.stock
        if target.stock_date is None or (
            other.stock_date is not None and other.stock_date > target.stock_date
        ):
            target.stock_date = other.stock_date


def _ratio(part: float | Decimal, whole: float | Decimal, scale: int = 1) -> float | None:
    """``part / whole x scale``, rounded to cents; ``None`` without a denominator."""
    if not whole:
        return None
    return round(float(part) / float(whole) * scale, 2)


def _order_sum(f: Facts) -> float | None:
    """Orders at the seller's price; ``None`` when orders exist but none was priced."""
    if not f.funnel_days:
        return None
    if f.orders == 0:
        return 0.0
    if f.priced_orders == 0:
        return None
    return round(float(f.amount_seller), 2)


def _seller_price(f: Facts) -> float | None:
    """Order-weighted price before СПП; the plain mean of snapshots on a no-order cell."""
    if f.priced_orders:
        return _ratio(f.amount_seller, f.priced_orders)
    return _ratio(f.seller_price_sum, f.seller_price_n)


def _customer_price(f: Facts) -> float | None:
    """Order-weighted price after СПП, with the same fallback."""
    if f.paid_orders:
        return _ratio(f.amount_paid, f.paid_orders)
    return _ratio(f.customer_price_sum, f.customer_price_n)


def _spp(f: Facts) -> float | None:
    """WB's discount as a share of the seller's price."""
    seller, customer = _seller_price(f), _customer_price(f)
    if seller is None or customer is None:
        return None
    return _ratio(seller - customer, seller, 100)


def _ads(read: Callable[[Facts], float | None]) -> Callable[[Facts], float | None]:
    """Guard an advertising metric: a day with neither ads nor funnel is unknown.

    A SKU-day that ran no ads has no advertising row at all, so the funnel's
    presence is what says the day was harvested and the zero is real.
    """
    return lambda f: read(f) if (f.ad_days or f.funnel_days) else None


def _funnel(read: Callable[[Facts], float | None]) -> Callable[[Facts], float | None]:
    """Guard a funnel metric: no funnel row means WB did not report the day."""
    return lambda f: read(f) if f.funnel_days else None


def _profit(f: Facts) -> float | None:
    """Payout net of WB's charges, less the goods' cost and the settled days' ads."""
    if not f.finance_known or f.uncosted:
        return None
    return round(float(f.payout_net - f.cogs - f.settled_spend), 2)


def _margin(f: Facts) -> float | None:
    """Profit as a share of revenue; undefined on a refund-only cell."""
    profit = _profit(f)
    if profit is None or f.revenue <= 0:
        return None
    return _ratio(profit, f.revenue, 100)


_READERS: dict[str, Callable[[Facts], float | None]] = {
    "orders": _funnel(lambda f: f.orders),
    "order_sum": _order_sum,
    "opens": _funnel(lambda f: f.opens),
    "carts": _funnel(lambda f: f.carts),
    "cart_conversion": _funnel(lambda f: _ratio(f.carts, f.opens, 100)),
    "order_conversion": _funnel(lambda f: _ratio(f.orders, f.carts, 100)),
    # WB's opens include the ad clicks; what is left is the card's own pull.
    # Clamped, because the two feeds count a click slightly differently and a
    # negative organic figure would be a measurement artefact, not a finding.
    "organic_opens": _funnel(lambda f: max(f.opens - f.ad_clicks, 0)),
    "spend": _ads(lambda f: round(float(f.spend), 2)),
    "ad_views": _ads(lambda f: f.ad_views),
    "ad_clicks": _ads(lambda f: f.ad_clicks),
    "ctr": _ads(lambda f: _ratio(f.ad_clicks, f.ad_views, 100)),
    "cpc": _ads(lambda f: _ratio(f.spend, f.ad_clicks)),
    "cpm": _ads(lambda f: _ratio(f.spend, f.ad_views, 1000)),
    "ad_orders": _ads(lambda f: f.ad_orders),
    "ad_cr": _ads(lambda f: _ratio(f.ad_orders, f.ad_clicks, 100)),
    "cpo": _ads(lambda f: _ratio(f.spend, f.ad_orders)),
    "drr_orders": _ads(lambda f: _ratio(f.spend, _order_sum(f) or 0, 100)),
    "seller_price": _seller_price,
    "customer_price": _customer_price,
    "spp": _spp,
    "stock": lambda f: f.stock,
    "revenue": lambda f: round(float(f.revenue), 2) if f.finance_known else None,
    "sales": lambda f: f.sold_units if f.finance_known else None,
    "profit": _profit,
    "margin": _margin,
}


def read_metric(key: str, facts: Facts) -> float | None:
    """Derive one metric from a cell's facts.

    Raises:
        KeyError: ``key`` is not a metric — the route's ``Literal`` makes that
            unreachable from HTTP.
    """
    value = _READERS[key](facts)
    return None if value is None else float(value)
