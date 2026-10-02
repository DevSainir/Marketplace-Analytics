"""Per-cell metric formulas of the display matrix.

One function per column family: the advertising buckets (:func:`_ad_cell`),
the «Общая» column (:func:`_total_cell`), the «Органика» column
(:func:`_organic_cell`), and the campaign-level «ДРР от продаж»
(:func:`_campaign_drr_sales`). All of them resolve manually edited display
values through :func:`_shown`, so a ratio never contradicts the cells it
divides.

No formula here adds or divides money of two currencies: a spend sum over
campaigns billed differently, and a ДРР whose spend and order money differ,
are «—» (see :mod:`~src.modules.monitoring.services.matrix.currency`).
"""

from __future__ import annotations

from src.modules.monitoring.schemas.matrix import MatrixDayBase, MatrixFunnelBase
from src.modules.monitoring.services.matrix.currency import (
    card_ad_currencies,
    pairs_with_orders,
    spend_is_mixed,
)
from src.modules.monitoring.services.matrix.pricing import (
    _buyout_sum,
    _funnel_order_sum,
    _funnel_spp,
    ad_buyout_sum,
    ad_order_sum,
)
from src.modules.monitoring.services.matrix.slices import _BucketAcc, _percent, _ratio, _SkuSlice

#: Metrics that are a spend sum or divide one — «—» when the spend they sum was
#: billed in two currencies.
_SPEND_METRICS: frozenset[str] = frozenset(
    {"spend", "cpm", "cpc", "cost_per_order", "cost_per_cart"}
)


def _shown(day: MatrixDayBase, bucket: str, metric: str, computed: float | None) -> float | None:
    """The value a cell actually SHOWS — a manual display override wins.

    The ДРР rows divide the spend and revenue printed above them in the same
    column, so they resolve their inputs through this. Cells whose value cannot
    be back-solved into a fact (the «Общая» spend roll-up, a buyout volume) are
    stored as display overrides; without this they would be painted on screen
    while the ratio underneath kept quoting the untouched computation.
    """
    override = day.cell_overrides.get(f"{bucket}:{metric}")
    return computed if override is None else override


def _ad_cell(
    key: str, acc: _BucketAcc | None, bid_type_views: int, day: MatrixDayBase, bucket: str
) -> float | None:
    """Compute one metric for an advertising bucket cell.

    ``bid_type_views`` is the total Показы of the bucket's bid type (unified or
    manual) that day — «Доля трафика» is normalized WITHIN a type, so Единая and
    Ручной each sum to 100%.

    ``day`` carries the price and the lagged buyout percent the revenue rows are
    derived from (see :func:`ad_order_sum`).

    Every metric here is the кампания's — an ad bucket carries no other kind
    (see :class:`~...slices._AdSlice`) — so every ratio describes what the
    campaign spent and brought, not the fraction of it that happened to be
    booked on the card on screen. The card's own share is emitted separately by
    the ``carts_sku``/``orders_sku`` rows, which the hover reports as the
    associated split.

    ``None`` (rendered «—») when no campaign of the bucket delivered that day, or
    the metric is not obtainable for ad buckets («Процент выкупа» is a
    SKU-level cohort window, not a per-campaign fact).
    """
    if acc is None:
        return None
    codes = sorted(acc.currencies)
    if key in _SPEND_METRICS and spend_is_mixed(codes):
        return None  # CONVERSION-TODO: spend of two currencies in one cell
    match key:
        case "traffic_share":
            return _percent(acc.views, bid_type_views)
        case "spend":
            return round(acc.spend, 2)
        case "views":
            return float(acc.views)
        case "ctr":
            return _percent(acc.clicks, acc.views)
        case "cpm":
            cpm = _ratio(acc.spend, acc.views)
            return None if cpm is None else round(cpm * 1000, 2)
        case "cpc":
            return _ratio(acc.spend, acc.clicks)
        case "clicks":
            return float(acc.clicks)
        case "carts":
            return float(acc.add_to_cart)
        case "carts_sku":
            # Emitted only when the campaign booked carts on OTHER variants —
            # the frontend reports the difference as the associated share.
            return float(acc.sku.add_to_cart) if acc.sku.add_to_cart < acc.add_to_cart else None
        case "cart_conversion":
            return _percent(acc.add_to_cart, acc.clicks)
        case "orders":
            return float(acc.orders)
        case "orders_sku":
            return float(acc.sku.orders) if acc.sku.orders < acc.orders else None
        case "order_conversion":
            return _percent(acc.orders, acc.add_to_cart)
        case "order_sum":  # orders x the day's order unit (WB reports none per zone)
            return ad_order_sum(acc.orders, day.funnel)
        case "buyout_sum":  # «Заказы» x «Процент выкупа»
            return ad_buyout_sum(acc.orders, day.funnel, day.lagged_buyout_percent)
        case "cost_per_order":
            return _ratio(acc.spend, acc.orders)
        case "cost_per_cart":
            return _ratio(acc.spend, acc.add_to_cart)
        case "drr_orders":  # this zone's spend against the orders IT delivered
            if not pairs_with_orders(codes, day):
                return None  # CONVERSION-TODO: spend and order money differ
            return _percent(
                _shown(day, bucket, "spend", acc.spend),
                _shown(day, bucket, "order_sum", ad_order_sum(acc.orders, day.funnel)),
            )
        case _:
            # buyout_percent is a SKU-level lagged cohort window, not a
            # per-campaign fact. (drr_sales never reaches here — it is computed
            # per campaign group in build_matrix_from_base.)
            return None


def _total_cell(
    key: str,
    day: MatrixDayBase,
    day_ad: _SkuSlice | None,
) -> float | None:
    """Compute one metric for the «Общая» column (funnel + cross-campaign ads).

    Count cells require a REAL funnel row (``has_funnel``) — a price-only day
    (the current day, funnel not served yet) renders its prices/СПП while the
    counts stay blank.

    The two ДРР rows read their spend and revenue through :func:`_shown`: this
    column's «Затраты, ₽» is a cross-campaign roll-up and its «Выкупы, ₽» a
    derived volume, neither of which back-solves into a fact, so both are
    edited as display overrides — and a ratio that ignored them would contradict
    the very cells it divides.
    """
    funnel = day.funnel
    lagged_buyout_percent = day.lagged_buyout_percent
    stock = day.stock
    counts = funnel if funnel is not None and funnel.has_funnel else None
    codes = card_ad_currencies(day)
    if key in _SPEND_METRICS and spend_is_mixed(codes):
        return None  # CONVERSION-TODO: the card's day spent in two currencies
    if key in ("drr_orders", "drr_sales") and not pairs_with_orders(codes, day):
        return None  # CONVERSION-TODO: spend and order money differ
    match key:
        case "spend":
            return None if day_ad is None else round(day_ad.spend, 2)
        case "views":
            return None if day_ad is None else float(day_ad.views)
        case "cpc":
            return None if day_ad is None else _ratio(day_ad.spend, day_ad.clicks)
        case "clicks":
            return None if counts is None else float(counts.open_count)
        case "carts":
            return None if counts is None else float(counts.cart_count)
        case "cart_conversion":
            return None if counts is None else _percent(counts.cart_count, counts.open_count)
        case "orders":
            return None if counts is None else float(counts.order_count)
        case "order_conversion":
            return None if counts is None else _percent(counts.order_count, counts.cart_count)
        case "order_sum":  # order_count x the day's order unit
            return _funnel_order_sum(funnel)
        case "buyout_sum":  # order-date: «Заказы» x «Процент выкупа»
            return _buyout_sum(funnel, lagged_buyout_percent)
        case "seller_price":
            return None if funnel is None else funnel.seller_price
        case "customer_price":
            return None if funnel is None else funnel.customer_price
        case "spp":  # (seller - customer) / seller x 100
            return _funnel_spp(funnel)
        case "cost_per_order":
            if day_ad is None or funnel is None:
                return None
            return _ratio(day_ad.spend, funnel.order_count)
        case "cost_per_cart":
            if day_ad is None or funnel is None:
                return None
            return _ratio(day_ad.spend, funnel.cart_count)
        case "drr_orders":  # all ad spend / the day's whole order revenue
            return _percent(
                _shown(day, "total", "spend", day_ad.spend if day_ad else None),
                _shown(day, "total", "order_sum", _funnel_order_sum(funnel)),
            )
        case "drr_sales":  # all ad spend / the day's whole buyout revenue
            return _percent(
                _shown(day, "total", "spend", day_ad.spend if day_ad else None),
                _shown(day, "total", "buyout_sum", _buyout_sum(funnel, lagged_buyout_percent)),
            )
        case "buyout_percent":
            return lagged_buyout_percent
        case "stock_quantity":
            return None if stock is None else float(stock.quantity)
        case "stock_to_client":
            return None if stock is None else float(stock.in_way_to_client)
        case "stock_from_client":
            return None if stock is None else float(stock.in_way_from_client)
        case "stock_total":  # остаток + в пути к клиенту + в пути от клиента
            if stock is None:
                return None
            return float(stock.quantity + stock.in_way_to_client + stock.in_way_from_client)
        case "ctr":
            # The ADVERTISING click-through rate, rolled up across the day's
            # campaigns — the same clicks over the same показы each ad bucket
            # divides, summed. It is emitted here even though this column's
            # «Клики» row shows the FUNNEL's clicks (organic included), so the
            # two do not reconcile: read it as «CTR рекламы за день», which is
            # what every ad bucket beside it already means.
            return None if day_ad is None else _percent(day_ad.clicks, day_ad.views)
        case "ad_clicks":  # the CTR's numerator, for its hover
            return None if day_ad is None else float(day_ad.clicks)
        case "cpm":
            # The day's whole advertising bill over the показы it bought —
            # built the same way as «CTR» above, as a ratio of SUMS.
            #
            # This column used to be blank on the grounds that a CPC campaign's
            # thousand-показов price cannot be averaged against a CPM one's.
            # That objection is about averaging the campaigns' own CPMs, which
            # this is not: spend over показы is what the seller actually paid
            # per thousand показов that day, and it stays a fact whatever the
            # billing models underneath it are. Read it as «CPM рекламы за
            # день», the way the CTR row beside it is read.
            cpm = _ratio(day_ad.spend if day_ad else None, day_ad.views if day_ad else None)
            return None if cpm is None else round(cpm * 1000, 2)
        case _:
            # traffic_share is defined across ad buckets only.
            return None


def _organic_cell(
    key: str, funnel: MatrixFunnelBase | None, day_ad: _SkuSlice | None
) -> float | None:
    """Compute one metric for the «Органика» column (общая - реклама).

    ``day_ad`` is the CARD's own advertising day, never the campaigns' — the
    funnel counts are the card's, so subtracting a campaign's all-variant
    conversions would credit this column with orders never booked here.
    """
    if funnel is None or not funnel.has_funnel:
        # No funnel counts (price-only day): «funnel - ads» would go negative.
        return None
    ad_clicks = day_ad.clicks if day_ad else 0
    ad_carts = day_ad.add_to_cart if day_ad else 0
    ad_orders = day_ad.orders if day_ad else 0
    match key:
        case "clicks":
            return float(funnel.open_count - ad_clicks)
        case "carts":
            return float(funnel.cart_count - ad_carts)
        case "orders":
            return float(funnel.order_count - ad_orders)
        case _:
            return None


#: The zone buckets of one campaign, per «тип получения трафика» group. «ДРР от
#: продаж» is a CAMPAIGN-level metric (WB never attributes buyouts to a zone):
#: every zone bucket of a group carries the same campaign-level value — the
#: group's total Затраты over the day's total «Выкупы, ₽» — and the frontend
#: renders the group as ONE merged cell.
_CAMPAIGN_ZONE_GROUPS: tuple[tuple[str, ...], ...] = (
    ("uni_search", "uni_shelves", "uni_catalog"),
    ("manual_search", "manual_catalog"),
    ("manual_shelves",),
    ("cpc_search", "cpc_shelves"),
)
_CAMPAIGN_GROUP_BY_BUCKET: dict[str, tuple[str, ...]] = {
    bucket: group for group in _CAMPAIGN_ZONE_GROUPS for bucket in group
}


def _campaign_drr_sales(
    bucket: str, day: MatrixDayBase, bucket_accs: dict[str, _BucketAcc]
) -> float | None:
    """«ДРР от продаж» of the campaign group an ad bucket belongs to.

    ``group spend / the group's OWN «Выкупы, ₽» x 100`` — the whole-campaign
    efficiency across all its view zones, repeated on each of the group's
    buckets so the frontend can merge them into one cell.

    Both sides are the campaign's: the denominator is the buyout value of the
    orders THIS campaign delivered (its all-variant orders x price x «Процент
    выкупа»), never the SKU's whole-day volume — dividing a campaign's spend by
    revenue the organic traffic brought would flatter every campaign on a good
    day.

    ``None`` when the group did not deliver that day, or the day is unpriced /
    has no buyout percent. The legacy «Каталог» uni zone stays empty as
    everywhere else — the merged cell reads the group's FIRST bucket, so it
    never needs the repeat there.
    """
    if bucket == "uni_catalog":
        return None
    group = _CAMPAIGN_GROUP_BY_BUCKET.get(bucket)
    if group is None:
        return None
    delivering = [name for name in group if name in bucket_accs]
    if not delivering:
        return None
    # Both sides are summed from what the zones SHOW, so a manually corrected
    # spend or buyout volume in any zone is the number this ratio divides.
    codes = sorted({code for name in delivering for code in bucket_accs[name].currencies})
    if not pairs_with_orders(codes, day):
        return None  # CONVERSION-TODO: spend and order money differ
    spend = sum(_shown(day, name, "spend", bucket_accs[name].spend) or 0.0 for name in delivering)
    buyout = sum(
        _shown(
            day,
            name,
            "buyout_sum",
            ad_buyout_sum(bucket_accs[name].orders, day.funnel, day.lagged_buyout_percent),
        )
        or 0.0
        for name in delivering
    )
    return _percent(spend, buyout)
