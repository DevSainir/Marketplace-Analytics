"""Pure builder for the day x traffic-bucket metrics matrix.

Composes three persisted fact families into the workbook-shaped matrix served
by the SKU detail endpoint:

* ``AdvertisingStatDaily`` — full per-campaign daily totals (all zones).
* ``AdvertisingSearchStatDaily`` — the SEARCH-zone slice of the same days
  (from WB's search-cluster stats endpoint).
* ``SalesFunnelDaily`` — the organic funnel («Общая» / «Органика» columns).

Campaign classification (via the ``Campaign`` dimension's adverts-v2 fields):

* ``manual`` bid + only the SHELVES placement -> the campaign's whole totals
  go to «Руч. полки».
* ``manual`` bid + only the SEARCH placement -> WB «поисковые» campaigns also
  deliver in the CATALOG zone (verified live: fullstats runs ~10-13% above the
  normquery sum), so the search slice goes to «Руч. поиск» and the remainder
  to «Руч. каталог». Without a harvested search slice (legacy rows) the whole
  day stays in «Руч. поиск» — misattributing ~90% of a search campaign to
  catalog would be worse than the old single-zone view.
* ``unified`` bid (always both zones) or a dual-placement manual campaign ->
  split: the search slice goes to the «Поиск» column, the remainder
  (``fullstats - search``, clamped at zero) to «Полки». WB exposes no
  zone-attributed order revenue, so a split campaign's ``order_sum`` taints its
  buckets' revenue cells to ``None`` («—») instead of guessing.

Significant-campaign selection (see :func:`_select_day_buckets`): a SKU
realistically has one — at most two — campaigns actually bringing traffic, so per
day only the leading campaign (by Показы) is kept, plus a second campaign when
its Показы clear :data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. A
surviving campaign keeps ALL its zones (a unified campaign's WB search/shelves
split is shown even at 99/1). Cut campaigns are excluded from «Общая»/«Органика»
too. «Доля трафика» is normalized WITHIN each bid type, so Единая and Ручной each
sum to 100%.

Everything here is pure computation over already-fetched rows: no SQL, no I/O.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.advertising import CampaignDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MATRIX_METRIC_KEYS,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
    MatrixMetricRow,
    MatrixStockBase,
    MetricsMatrixRead,
)

#: «Процент выкупа» is WB's definition (buyouts / DECIDED deliveries) averaged
#: over a lagged cohort window: recent order cohorts are still maturing (their
#: deliveries take 1-3 weeks to be accepted or refused), so for a day D the
#: window is ``[D - 21, D - 7]`` (e.g. for 10 July: 19 June .. 03 July).
BUYOUT_LAG_START_DAYS = 21
BUYOUT_LAG_END_DAYS = 7


@dataclass
class _AdSlice:
    """Advertising metrics of one campaign-day (or a zone slice of it).

    ``order_sum`` is ``None`` when the slice's revenue cannot be attributed to
    its zone (a split campaign) — the taint propagates to the bucket.

    ``assoc_add_to_cart``/``assoc_orders`` are the campaign-level conversion
    totals INCLUDING associated size/colour variants («ассоциированные
    конверсии» — WB books a conversion on whichever variant the buyer picked,
    so only part of a campaign's carts/orders land on the advertised SKU).
    They always satisfy ``assoc_x >= x`` for a whole campaign-day slice.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    assoc_add_to_cart: int = 0
    assoc_orders: int = 0


@dataclass
class _BucketAcc:
    """Accumulated advertising metrics of one (day, bucket) cell."""

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0
    assoc_add_to_cart: int = 0
    assoc_orders: int = 0

    def add(self, piece: _AdSlice) -> None:
        """Fold a campaign slice into the bucket (revenue taint propagates)."""
        self.views += piece.views
        self.clicks += piece.clicks
        self.add_to_cart += piece.add_to_cart
        self.spend += piece.spend
        self.orders += piece.orders
        self.assoc_add_to_cart += piece.assoc_add_to_cart
        self.assoc_orders += piece.assoc_orders
        if piece.order_sum is None:
            self.order_sum = None
        elif self.order_sum is not None:
            self.order_sum += piece.order_sum


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator, or ``None`` when it cannot be computed."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, 2)


def _percent(numerator: float | None, denominator: float | None) -> float | None:
    """Numerator / denominator as a percentage, or ``None`` on ÷0."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _day_range(date_from: date, date_to: date) -> list[date]:
    """Inclusive day sequence ``date_from..date_to``."""
    return [date_from + timedelta(days=offset) for offset in range((date_to - date_from).days + 1)]


def _allocate_assoc(extra: int, s_metric: int, total_metric: int, view_share: float) -> int:
    """Portion of the associative EXTRA conversions allocated to the search leg.

    WB reports associated-variant conversions only at campaign level (the
    normquery search slice tracks the advertised SKU's own conversions — see
    the live data: search carts never exceed the SKU's), so a split
    campaign-day's extra has no exact zone attribution. It is apportioned by
    the SKU's own zone split of the same metric — the best available estimator
    of where the delivering clicks were — falling back to the view share when
    the SKU itself had none of the metric. Leg sums stay exact by construction
    (shelves takes the remainder).
    """
    share = s_metric / total_metric if total_metric > 0 else view_share
    return min(extra, max(0, round(extra * share)))


def _split_search(
    total: _AdSlice, search: AdvertisingSearchStatDaily | None
) -> tuple[_AdSlice, _AdSlice]:
    """Split a dual-zone campaign-day into (search, shelves) slices.

    The search slice is clamped per-metric at the campaign total (the two
    sources are collected at different times, so tiny attribution drifts can
    put a click in one report before the other); the shelves slice is the
    remainder. Zone-attributed order revenue does not exist: both slices carry
    ``order_sum=None`` unless the campaign-day had no revenue at all. The
    associative totals ride the same split (see :func:`_allocate_assoc`).
    """
    s_views = min(search.views, total.views) if search else 0
    s_clicks = min(search.clicks, total.clicks) if search else 0
    s_atbs = min(search.add_to_cart, total.add_to_cart) if search else 0
    s_spend = min(float(search.spend), total.spend) if search else 0.0
    s_orders = min(search.orders, total.orders) if search else 0
    revenue: float | None = 0.0 if not total.order_sum else None
    view_share = s_views / total.views if total.views > 0 else 0.0
    extra_carts = max(0, total.assoc_add_to_cart - total.add_to_cart)
    extra_orders = max(0, total.assoc_orders - total.orders)
    s_extra_carts = _allocate_assoc(extra_carts, s_atbs, total.add_to_cart, view_share)
    s_extra_orders = _allocate_assoc(extra_orders, s_orders, total.orders, view_share)
    search_slice = _AdSlice(
        views=s_views,
        clicks=s_clicks,
        add_to_cart=s_atbs,
        spend=s_spend,
        orders=s_orders,
        order_sum=revenue,
        assoc_add_to_cart=s_atbs + s_extra_carts,
        assoc_orders=s_orders + s_extra_orders,
    )
    shelves_slice = _AdSlice(
        views=total.views - s_views,
        clicks=total.clicks - s_clicks,
        add_to_cart=total.add_to_cart - s_atbs,
        spend=round(total.spend - s_spend, 2),
        orders=total.orders - s_orders,
        order_sum=revenue,
        assoc_add_to_cart=(total.add_to_cart - s_atbs) + (extra_carts - s_extra_carts),
        assoc_orders=(total.orders - s_orders) + (extra_orders - s_extra_orders),
    )
    return search_slice, shelves_slice


def _classify(
    meta: Campaign | None,
    total: _AdSlice,
    search: AdvertisingSearchStatDaily | None,
) -> list[tuple[str, _AdSlice]]:
    """Assign a campaign-day's metrics to matrix buckets.

    Returns ``(bucket_key, slice)`` legs; empty when the campaign cannot be
    classified (settings never synced) — it then only feeds the day totals.
    """
    if meta is None or not meta.bid_type:
        return []
    in_search = bool(meta.placement_search)
    in_shelves = bool(meta.placement_recommendations)
    unified = meta.bid_type == "unified"
    if in_search and in_shelves:
        search_slice, shelves_slice = _split_search(total, search)
        if unified:
            return [("uni_search", search_slice), ("uni_shelves", shelves_slice)]
        return [("manual_search", search_slice), ("manual_shelves", shelves_slice)]
    if unified:
        # Defensive: live unified campaigns always run in both zones, but obey
        # the flags if WB ever ships a single-zone unified campaign.
        return [("uni_search" if in_search else "uni_shelves", total)]
    if in_search:
        # WB «поисковые» campaigns also deliver in the CATALOG zone: the
        # normquery slice is «Поиск», the remainder «Каталог». Without a
        # harvested slice for this campaign-day (legacy rows), keep the whole
        # day in «Руч. поиск» — a missing slice must not shove ~90% of a
        # search campaign into catalog.
        if search is None:
            return [("manual_search", total)]
        search_slice, catalog_slice = _split_search(total, search)
        return [("manual_search", search_slice), ("manual_catalog", catalog_slice)]
    if in_shelves:
        return [("manual_shelves", total)]
    return []


def _ad_cell(key: str, acc: _BucketAcc | None, bid_type_views: int) -> float | None:
    """Compute one metric for an advertising bucket cell.

    ``bid_type_views`` is the total Показы of the bucket's bid type (unified or
    manual) that day — «Доля трафика» is normalized WITHIN a type, so Единая and
    Ручной each sum to 100%.

    ``None`` (rendered «—») when no campaign of the bucket delivered that day, or
    the metric is not obtainable for ad buckets (buyouts are funnel-only, revenue
    is untracked for split zones).
    """
    if acc is None:
        return None
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
        case "carts_assoc":
            # Emitted only when associated variants actually converted — the
            # frontend then decorates the carts cell as «assoc(sku)».
            return float(acc.assoc_add_to_cart) if acc.assoc_add_to_cart > acc.add_to_cart else None
        case "cart_conversion":
            return _percent(acc.add_to_cart, acc.clicks)
        case "orders":
            return float(acc.orders)
        case "orders_assoc":
            return float(acc.assoc_orders) if acc.assoc_orders > acc.orders else None
        case "order_conversion":
            return _percent(acc.orders, acc.add_to_cart)
        case "order_sum":
            return None if acc.order_sum is None else round(acc.order_sum, 2)
        case "cost_per_order":
            return _ratio(acc.spend, acc.orders)
        case "cost_per_cart":
            return _ratio(acc.spend, acc.add_to_cart)
        case "drr_orders":
            return _percent(acc.spend, acc.order_sum)
        case _:
            # buyout_sum / buyout_percent / drr_sales: buyouts are not
            # attributable to advertising zones.
            return None


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


def _total_cell(
    key: str,
    funnel: MatrixFunnelBase | None,
    day_ad: _BucketAcc | None,
    lagged_buyout_percent: float | None,
    stock: MatrixStockBase | None,
) -> float | None:
    """Compute one metric for the «Общая» column (funnel + cross-campaign ads).

    Count cells require a REAL funnel row (``has_funnel``) — a price-only day
    (the current day, funnel not served yet) renders its prices/СПП while the
    counts stay blank.
    """
    counts = funnel if funnel is not None and funnel.has_funnel else None
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
        case "order_sum":  # order_count x seller_price
            return _funnel_order_sum(funnel)
        case "buyout_sum":  # order-date: «Заказы, ₽» x «Процент выкупа»
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
        case "drr_orders":
            if day_ad is None or funnel is None:
                return None
            return _percent(day_ad.spend, _funnel_order_sum(funnel))
        case "drr_sales":
            if day_ad is None:
                return None
            return _percent(day_ad.spend, _buyout_sum(funnel, lagged_buyout_percent))
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
        case _:
            # traffic_share is defined across ad buckets only; CTR/CPM have no
            # meaning for the mixed «Общая» column.
            return None


def _organic_cell(
    key: str, funnel: MatrixFunnelBase | None, day_ad: _BucketAcc | None
) -> float | None:
    """Compute one metric for the «Органика» column (общая - реклама)."""
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


def _bucket_base(acc: _AdSlice | _BucketAcc) -> MatrixAdBucketBase:
    """Freeze an ad slice / bucket accumulator into a serializable input DTO."""
    return MatrixAdBucketBase(
        views=acc.views,
        clicks=acc.clicks,
        add_to_cart=acc.add_to_cart,
        spend=round(acc.spend, 2),
        orders=acc.orders,
        order_sum=None if acc.order_sum is None else round(acc.order_sum, 2),
        assoc_add_to_cart=acc.assoc_add_to_cart,
        assoc_orders=acc.assoc_orders,
    )


#: A second campaign is kept only when its Показы are at least this fraction of
#: the LEADING campaign's; below it the campaign is noise and cut («—»). Chosen
#: from the live data: real second campaigns sit at ≥0.145 of the leader (with
#: thousands of ₽ and 100+ clicks), noise seconds at ≤0.022 — a wide empty gap,
#: so 0.10 separates them robustly. Tunable.
_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO = 0.10


def _select_day_buckets(
    campaigns_today: list[tuple[_AdSlice, list[tuple[str, _AdSlice]]]],
) -> dict[str, MatrixAdBucketBase]:
    """Keep only the significant campaign(s) for a day, cutting the noise.

    A SKU realistically has one — at most two — campaigns actually bringing
    traffic (a paused campaign can still deliver, so status is ignored; only real
    paid delivery counts). Campaigns are ranked by Показы; the leader is kept,
    and a second is kept only when its Показы are at least
    :data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. Everything else is
    dropped («—»).

    A surviving campaign keeps ALL its zones: a unified campaign's WB search /
    shelves split is shown in full (even a 99/1 split), because that division is
    WB's own. A zone leg with no impressions is omitted (nothing to show).

    Args:
        campaigns_today: One ``(campaign total, zone legs)`` entry per delivering
            campaign that day. A unified campaign's legs are its search + shelves
            slices; a manual campaign's is its single zone.

    Returns:
        The surviving ``bucket_key -> input DTO`` map.
    """
    candidates = [
        (total, legs) for total, legs in campaigns_today if total.views > 0 and total.spend > 0
    ]
    candidates.sort(key=lambda entry: entry[0].views, reverse=True)
    if not candidates:
        return {}

    kept = [candidates[0]]
    leader_views = candidates[0][0].views
    if len(candidates) > 1 and (
        candidates[1][0].views >= _SECONDARY_MIN_CAMPAIGN_VIEW_RATIO * leader_views
    ):
        kept.append(candidates[1])

    bucket_acc: dict[str, _BucketAcc] = {}
    for _total, legs in kept:
        for bucket_key, slice_ in legs:
            if slice_.views <= 0:
                continue  # no impressions in this zone -> nothing to show
            bucket_acc.setdefault(bucket_key, _BucketAcc()).add(slice_)
    return {name: _bucket_base(acc) for name, acc in bucket_acc.items()}


def derive_base_state(
    *,
    date_from: date,
    date_to: date,
    funnel_rows: list[SalesFunnelDaily],
    ad_rows: list[AdvertisingStatDaily],
    search_rows: list[AdvertisingSearchStatDaily],
    campaigns: dict[int, Campaign],
    price_snapshots: list[PriceSnapshot] | None = None,
    stock_daily: list[StockDailyTotal] | None = None,
    campaign_totals: list[CampaignDayTotal] | None = None,
) -> MatrixBaseState:
    """Aggregate raw facts into the editable input working copy.

    This is the first of the two matrix stages: it does all the campaign
    classification, the unified search/shelves split, and the lagged buyout
    window, then freezes the result into the per-day input facts. The second
    stage (:func:`build_matrix_from_base`) derives the display matrix from it.
    Isolating the inputs is what lets the frontend edit them and have the
    server recompute the dependents.

    Args:
        date_from: Inclusive window start (first day column).
        date_to: Inclusive window end (last day column).
        funnel_rows: Daily funnel rows covering the EXTENDED window
            ``[date_from - 21, date_to]`` — the lagged «Процент выкупа» reads up
            to 21 days before the first displayed day.
        ad_rows: The SKU's advertising fact rows within the window.
        search_rows: The SKU's search-zone slices within the window.
        campaigns: Campaign metadata keyed by ``campaign_id`` (may be partial).
        price_snapshots: The SKU's seller/customer price snapshots; applied
            only to their exact snapshot days (pricing «Заказы, ₽» and «СПП»
            there; other days stay unpriced).
        stock_daily: The SKU's per-day stock totals; applied only to their
            exact snapshot days for the read-only stock/in-transit rows.
        campaign_totals: Per-(campaign, day) conversion totals across ALL
            nm_ids — the associative-conversion «100» shown next to the SKU's
            own «71». Missing entries mean no associative gap for that slice.

    Returns:
        The :class:`MatrixBaseState` working copy for the window.
    """
    days = _day_range(date_from, date_to)
    funnel_by_date = {row.stat_date: row for row in funnel_rows}
    ordered_prices = sorted(price_snapshots or [], key=lambda s: s.stat_date)
    ordered_stock = sorted(stock_daily or [], key=lambda s: s.stat_date)

    # One slice per (campaign, day), aggregated across platforms.
    campaign_day: dict[tuple[int, date], _AdSlice] = {}
    for row in ad_rows:
        total = campaign_day.setdefault((row.campaign_id, row.stat_date), _AdSlice())
        total.views += row.views
        total.clicks += row.clicks
        total.add_to_cart += row.add_to_cart
        total.spend += float(row.spend)
        total.orders += row.orders
        if total.order_sum is not None:
            total.order_sum += float(row.order_sum)

    # Stamp the associative (all-variant) conversion totals onto each slice.
    # Clamped from below at the SKU's own counts so a partial totals fetch can
    # never show an associative total smaller than the SKU slice itself.
    totals_by_key = {(t.campaign_id, t.stat_date): t for t in campaign_totals or []}
    for key, total in campaign_day.items():
        campaign_total = totals_by_key.get(key)
        total.assoc_add_to_cart = max(
            campaign_total.add_to_cart if campaign_total else 0, total.add_to_cart
        )
        total.assoc_orders = max(campaign_total.orders if campaign_total else 0, total.orders)

    search_by_key = {(row.campaign_id, row.stat_date): row for row in search_rows}

    # Classify each campaign-day into its display-zone leg(s): a manual campaign
    # yields one leg, a dual-zone (unified) campaign a search + a shelves slice.
    # Collected per day (with the campaign total) so the significant campaign(s)
    # can be selected.
    day_campaigns: dict[date, list[tuple[_AdSlice, list[tuple[str, _AdSlice]]]]] = defaultdict(list)
    for (campaign_id, stat_date), total in campaign_day.items():
        legs = _classify(
            campaigns.get(campaign_id), total, search_by_key.get((campaign_id, stat_date))
        )
        if legs:  # unclassifiable campaigns (no settings) are excluded entirely
            day_campaigns[stat_date].append((total, legs))

    day_bases: list[MatrixDayBase] = []
    for day in days:
        # Keep only the significant campaign(s) (cut insignificant traffic). Cut
        # campaigns are excluded from «Общая»/«Органика» too, so the unclassified
        # remainder is empty and each bid type's «Доля трафика» sums to 100%.
        buckets = _select_day_buckets(day_campaigns.get(day, []))

        funnel_row = funnel_by_date.get(day)
        seller_price, customer_price = price_for_day(ordered_prices, day)
        if funnel_row is not None:
            funnel_base = MatrixFunnelBase(
                open_count=funnel_row.open_count,
                cart_count=funnel_row.cart_count,
                order_count=funnel_row.order_count,
                seller_price=seller_price,
                customer_price=customer_price,
            )
        elif seller_price is not None or customer_price is not None:
            # No funnel row yet (the CURRENT day — WB serves the funnel a day
            # late) but the day's prices were snapshotted at harvest: carry a
            # price-only base so «Цены»/«СПП» render while the count cells
            # stay blank and read-only.
            funnel_base = MatrixFunnelBase(
                seller_price=seller_price,
                customer_price=customer_price,
                has_funnel=False,
            )
        else:
            funnel_base = None

        # «Процент выкупа»: WB's definition — buyouts / DECIDED deliveries —
        # averaged over the lagged [D-21, D-7] cohort window (recent cohorts
        # are still maturing). Each funnel day stores WB's own cohort percent
        # (`buyout_conversion`); deliveries are recovered per cohort as
        # `buyout_count / percent`, then the window is aggregated weighted.
        window_start = day - timedelta(days=BUYOUT_LAG_START_DAYS)
        window_end = day - timedelta(days=BUYOUT_LAG_END_DAYS)
        buyouts = 0.0
        delivered = 0.0
        for funnel_row in funnel_rows:
            if not (window_start <= funnel_row.stat_date <= window_end):
                continue
            count = funnel_row.buyout_count
            wb_percent = float(funnel_row.buyout_conversion or 0)
            if count > 0 and wb_percent > 0:
                buyouts += count
                delivered += count * 100.0 / wb_percent

        day_bases.append(
            MatrixDayBase(
                day=day,
                has_advertising=bool(buckets),
                buckets=buckets,
                unclassified=MatrixAdBucketBase(),  # cut campaigns are excluded
                funnel=funnel_base,
                lagged_buyout_percent=_percent(buyouts, delivered),
                stock=_stock_for_day(ordered_stock, day),
            )
        )

    return MatrixBaseState(days=day_bases)


def _acc_from_base(base: MatrixAdBucketBase) -> _BucketAcc:
    """Rehydrate a bucket accumulator from its input DTO."""
    return _BucketAcc(
        views=base.views,
        clicks=base.clicks,
        add_to_cart=base.add_to_cart,
        spend=base.spend,
        orders=base.orders,
        order_sum=base.order_sum,
        assoc_add_to_cart=base.assoc_add_to_cart,
        assoc_orders=base.assoc_orders,
    )


def _day_ad_from_base(day: MatrixDayBase) -> _BucketAcc | None:
    """Reconstruct a day's overall ad totals = Σ buckets + unclassified.

    Returns ``None`` for days with no advertising at all, so «Общая» ad cells
    render «—» exactly as before (a zero accumulator would show ``0``).
    """
    if not day.has_advertising:
        return None
    total = _BucketAcc()
    for base in (*day.buckets.values(), day.unclassified):
        total.views += base.views
        total.clicks += base.clicks
        total.add_to_cart += base.add_to_cart
        total.spend += base.spend
        total.orders += base.orders
    return total


def build_matrix_from_base(base: MatrixBaseState) -> MetricsMatrixRead:
    """Derive the display matrix from an (edited) input working copy.

    The second matrix stage: pure derivation, no aggregation. Reused verbatim by
    both the read path (after overlaying overrides) and the preview path (after
    applying a pending edit), so every consumer sees identical formulas.

    Args:
        base: The input working copy (as produced by :func:`derive_base_state`,
            possibly with edits applied).

    Returns:
        A fully computed :class:`MetricsMatrixRead`.
    """
    days = [day.day for day in base.days]
    rows: list[MatrixMetricRow] = []
    for key in MATRIX_METRIC_KEYS:
        values: list[float | None] = []
        for day in base.days:
            day_ad = _day_ad_from_base(day)
            bucket_accs = {name: _acc_from_base(b) for name, b in day.buckets.items()}
            # «Доля трафика» is normalized within each bid type (Единая / Ручной
            # each sum to 100%), so precompute per-type total Показы.
            type_views = {
                "uni": sum(b.views for n, b in day.buckets.items() if n.startswith("uni_")),
                "manual": sum(b.views for n, b in day.buckets.items() if n.startswith("manual_")),
            }
            for bucket in MATRIX_BUCKETS:
                if bucket == "total":
                    value = _total_cell(
                        key,
                        day.funnel,
                        day_ad,
                        day.lagged_buyout_percent,
                        day.stock,
                    )
                elif bucket == "organic":
                    value = _organic_cell(key, day.funnel, day_ad)
                else:
                    bid_views = type_views["uni" if bucket.startswith("uni_") else "manual"]
                    value = _ad_cell(key, bucket_accs.get(bucket), bid_views)
                # A manual display override wins over the computed value, so any
                # non-invertible cell can still be edited (shown verbatim).
                override = day.cell_overrides.get(f"{bucket}:{key}")
                values.append(value if override is None else override)
        rows.append(MatrixMetricRow(key=key, values=values))

    return MetricsMatrixRead(days=days, buckets=list(MATRIX_BUCKETS), rows=rows)


def build_metrics_matrix(
    *,
    date_from: date,
    date_to: date,
    funnel_rows: list[SalesFunnelDaily],
    ad_rows: list[AdvertisingStatDaily],
    search_rows: list[AdvertisingSearchStatDaily],
    campaigns: dict[int, Campaign],
    price_snapshots: list[PriceSnapshot] | None = None,
    stock_daily: list[StockDailyTotal] | None = None,
    campaign_totals: list[CampaignDayTotal] | None = None,
) -> MetricsMatrixRead:
    """Build the complete day x bucket metrics matrix for one SKU.

    Thin wrapper over the two matrix stages (:func:`derive_base_state` then
    :func:`build_matrix_from_base`) — the direct facts-to-matrix path used where
    no editing is involved.

    Args:
        date_from: Inclusive window start (first day column).
        date_to: Inclusive window end (last day column).
        funnel_rows: Daily funnel rows covering the EXTENDED window
            ``[date_from - 21, date_to]``.
        ad_rows: The SKU's advertising fact rows within the window.
        search_rows: The SKU's search-zone slices within the window.
        campaigns: Campaign metadata keyed by ``campaign_id`` (may be partial).
        price_snapshots: The SKU's seller/customer price snapshots.
        stock_daily: The SKU's per-day stock totals.
        campaign_totals: Per-(campaign, day) all-variant conversion totals
            (the associative-conversion display).

    Returns:
        A fully computed :class:`MetricsMatrixRead`.
    """
    return build_matrix_from_base(
        derive_base_state(
            date_from=date_from,
            date_to=date_to,
            funnel_rows=funnel_rows,
            ad_rows=ad_rows,
            search_rows=search_rows,
            campaigns=campaigns,
            price_snapshots=price_snapshots,
            stock_daily=stock_daily,
            campaign_totals=campaign_totals,
        )
    )
