"""Pure builder for the day x traffic-bucket metrics matrix.

Composes three persisted fact families into the workbook-shaped matrix served
by the SKU detail endpoint:

* ``AdvertisingStatDaily`` — full per-campaign daily totals (all zones).
* ``AdvertisingSearchStatDaily`` — the SEARCH-zone slice of the same days
  (from WB's search-cluster stats endpoint).
* ``SalesFunnelDaily`` — the organic funnel («Общая» / «Органика» columns).

Campaign classification (via the ``Campaign`` dimension's adverts-v2 fields):

* ``manual`` bid + a single enabled placement -> the campaign's whole totals go
  to «Руч. поиск» or «Руч. полки».
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
    SalesFunnelDaily,
)
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MATRIX_METRIC_KEYS,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
    MatrixMetricRow,
    MetricsMatrixRead,
)

#: «Процент выкупа» is computed over a lagged window because buyouts trail
#: orders by roughly the delivery time: for a day D the window is
#: ``[D - 21, D - 7]`` (e.g. for 10 July: 19 June .. 03 July).
BUYOUT_LAG_START_DAYS = 21
BUYOUT_LAG_END_DAYS = 7


@dataclass
class _AdSlice:
    """Advertising metrics of one campaign-day (or a zone slice of it).

    ``order_sum`` is ``None`` when the slice's revenue cannot be attributed to
    its zone (a split campaign) — the taint propagates to the bucket.
    """

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0


@dataclass
class _BucketAcc:
    """Accumulated advertising metrics of one (day, bucket) cell."""

    views: int = 0
    clicks: int = 0
    add_to_cart: int = 0
    spend: float = 0.0
    orders: int = 0
    order_sum: float | None = 0.0

    def add(self, piece: _AdSlice) -> None:
        """Fold a campaign slice into the bucket (revenue taint propagates)."""
        self.views += piece.views
        self.clicks += piece.clicks
        self.add_to_cart += piece.add_to_cart
        self.spend += piece.spend
        self.orders += piece.orders
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


def _split_search(
    total: _AdSlice, search: AdvertisingSearchStatDaily | None
) -> tuple[_AdSlice, _AdSlice]:
    """Split a dual-zone campaign-day into (search, shelves) slices.

    The search slice is clamped per-metric at the campaign total (the two
    sources are collected at different times, so tiny attribution drifts can
    put a click in one report before the other); the shelves slice is the
    remainder. Zone-attributed order revenue does not exist: both slices carry
    ``order_sum=None`` unless the campaign-day had no revenue at all.
    """
    s_views = min(search.views, total.views) if search else 0
    s_clicks = min(search.clicks, total.clicks) if search else 0
    s_atbs = min(search.add_to_cart, total.add_to_cart) if search else 0
    s_spend = min(float(search.spend), total.spend) if search else 0.0
    s_orders = min(search.orders, total.orders) if search else 0
    revenue: float | None = 0.0 if not total.order_sum else None
    search_slice = _AdSlice(
        views=s_views,
        clicks=s_clicks,
        add_to_cart=s_atbs,
        spend=s_spend,
        orders=s_orders,
        order_sum=revenue,
    )
    shelves_slice = _AdSlice(
        views=total.views - s_views,
        clicks=total.clicks - s_clicks,
        add_to_cart=total.add_to_cart - s_atbs,
        spend=round(total.spend - s_spend, 2),
        orders=total.orders - s_orders,
        order_sum=revenue,
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
        return [("manual_search", total)]
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
        case "cart_conversion":
            return _percent(acc.add_to_cart, acc.clicks)
        case "orders":
            return float(acc.orders)
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


def _total_cell(
    key: str,
    funnel: MatrixFunnelBase | None,
    day_ad: _BucketAcc | None,
    lagged_buyout_percent: float | None,
) -> float | None:
    """Compute one metric for the «Общая» column (funnel + cross-campaign ads)."""
    match key:
        case "spend":
            return None if day_ad is None else round(day_ad.spend, 2)
        case "views":
            return None if day_ad is None else float(day_ad.views)
        case "cpc":
            return None if day_ad is None else _ratio(day_ad.spend, day_ad.clicks)
        case "clicks":
            return None if funnel is None else float(funnel.open_count)
        case "carts":
            return None if funnel is None else float(funnel.cart_count)
        case "cart_conversion":
            return None if funnel is None else _percent(funnel.cart_count, funnel.open_count)
        case "orders":
            return None if funnel is None else float(funnel.order_count)
        case "order_conversion":
            return None if funnel is None else _percent(funnel.order_count, funnel.cart_count)
        case "order_sum":
            return None if funnel is None else round(float(funnel.order_sum), 2)
        case "buyout_sum":
            return None if funnel is None else round(float(funnel.buyout_sum), 2)
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
            return _percent(day_ad.spend, float(funnel.order_sum))
        case "drr_sales":
            if day_ad is None or funnel is None:
                return None
            return _percent(day_ad.spend, float(funnel.buyout_sum))
        case "buyout_percent":
            return lagged_buyout_percent
        case _:
            # traffic_share is defined across ad buckets only; CTR/CPM have no
            # meaning for the mixed «Общая» column.
            return None


def _organic_cell(
    key: str, funnel: MatrixFunnelBase | None, day_ad: _BucketAcc | None
) -> float | None:
    """Compute one metric for the «Органика» column (общая - реклама)."""
    if funnel is None:
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

    Returns:
        The :class:`MatrixBaseState` working copy for the window.
    """
    days = _day_range(date_from, date_to)
    funnel_by_date = {row.stat_date: row for row in funnel_rows}

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
        funnel_base = (
            MatrixFunnelBase(
                open_count=funnel_row.open_count,
                cart_count=funnel_row.cart_count,
                order_count=funnel_row.order_count,
                order_sum=round(float(funnel_row.order_sum), 2),
                buyout_sum=round(float(funnel_row.buyout_sum), 2),
            )
            if funnel_row is not None
            else None
        )

        # «Процент выкупа»: buyouts/orders over the lagged [D-21, D-7] window.
        window_start = day - timedelta(days=BUYOUT_LAG_START_DAYS)
        window_end = day - timedelta(days=BUYOUT_LAG_END_DAYS)
        buyouts = orders = 0
        for funnel_row in funnel_rows:
            if window_start <= funnel_row.stat_date <= window_end:
                buyouts += funnel_row.buyout_count
                orders += funnel_row.order_count

        day_bases.append(
            MatrixDayBase(
                day=day,
                has_advertising=bool(buckets),
                buckets=buckets,
                unclassified=MatrixAdBucketBase(),  # cut campaigns are excluded
                funnel=funnel_base,
                lagged_buyout_percent=_percent(buyouts, orders),
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
                    values.append(_total_cell(key, day.funnel, day_ad, day.lagged_buyout_percent))
                elif bucket == "organic":
                    values.append(_organic_cell(key, day.funnel, day_ad))
                else:
                    bid_views = type_views["uni" if bucket.startswith("uni_") else "manual"]
                    values.append(_ad_cell(key, bucket_accs.get(bucket), bid_views))
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
        )
    )
