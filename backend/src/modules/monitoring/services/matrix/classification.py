"""Classify campaign-days into display-zone buckets and keep the significant ones.

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
  (``fullstats - search``, clamped at zero) to «Полки».

Significant-campaign selection (see :func:`_select_day_buckets`): a SKU
realistically has one — at most two — campaigns actually bringing traffic. A
campaign-day must first spend at least :data:`_MIN_CAMPAIGN_DAY_SPEND` to count
as delivering; of those, only the leading campaign (by Показы) is kept, plus a
second campaign when its Показы clear
:data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. A surviving campaign
keeps ALL its zones (a unified campaign's WB search/shelves split is shown even
at 99/1). Cut campaigns are excluded from «Общая»/«Органика» too.
"""

from __future__ import annotations

from src.modules.monitoring.models import AdvertisingSearchStatDaily, Campaign
from src.modules.monitoring.schemas.matrix import AssocSkuCount, MatrixAdBucketBase
from src.modules.monitoring.services.matrix.assoc import _allocate_assoc, _split_assoc_skus
from src.modules.monitoring.services.matrix.slices import _AdSlice, _BucketAcc


def _split_search(
    total: _AdSlice, search: AdvertisingSearchStatDaily | None, viewed_nm: int | None = None
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
    # The associated variants' counts are apportioned — EXCEPT when a zone took
    # none of the extra (or all of it), where the division is forced and the
    # per-variant rows are as exact as the campaign-day's own.
    exact = s_extra_carts in (0, extra_carts) and s_extra_orders in (0, extra_orders)
    if viewed_nm is None:
        search_skus: dict[int, tuple[int, int]] = {}
        rest_skus: dict[int, tuple[int, int]] = {}
    else:
        search_skus, rest_skus = _split_assoc_skus(
            total.assoc_skus,
            viewed_nm=viewed_nm,
            search_own=(s_atbs, s_orders),
            search_extra=(s_extra_carts, s_extra_orders),
        )
    search_slice = _AdSlice(
        views=s_views,
        clicks=s_clicks,
        add_to_cart=s_atbs,
        spend=s_spend,
        orders=s_orders,
        order_sum=revenue,
        assoc_add_to_cart=s_atbs + s_extra_carts,
        assoc_orders=s_orders + s_extra_orders,
        assoc_skus=search_skus,
        assoc_exact=exact,
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
        assoc_skus=rest_skus,
        assoc_exact=exact,
    )
    return search_slice, shelves_slice


def _classify(
    meta: Campaign | None,
    total: _AdSlice,
    search: AdvertisingSearchStatDaily | None,
    viewed_nm: int | None = None,
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
        search_slice, shelves_slice = _split_search(total, search, viewed_nm)
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
        search_slice, catalog_slice = _split_search(total, search, viewed_nm)
        return [("manual_search", search_slice), ("manual_catalog", catalog_slice)]
    if in_shelves:
        return [("manual_shelves", total)]
    return []


def _assoc_sku_counts(
    acc: _AdSlice | _BucketAcc, sku_labels: dict[int, str | None] | None
) -> list[AssocSkuCount]:
    """Freeze a cell's per-variant breakdown, biggest contributor first."""
    labels = sku_labels or {}
    counts = [
        AssocSkuCount(nm_id=nm_id, vendor_code=labels.get(nm_id), add_to_cart=carts, orders=orders)
        for nm_id, (carts, orders) in acc.assoc_skus.items()
    ]
    # Carts first, then orders, then nm_id: a stable order that puts the rows
    # a reader cares about at the top and never reshuffles between renders.
    counts.sort(key=lambda c: (-c.add_to_cart, -c.orders, c.nm_id))
    return counts


def _bucket_base(
    acc: _AdSlice | _BucketAcc, sku_labels: dict[int, str | None] | None = None
) -> MatrixAdBucketBase:
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
        assoc_skus=_assoc_sku_counts(acc, sku_labels),
        assoc_exact=acc.assoc_exact,
    )


#: A second campaign is kept only when its Показы are at least this fraction of
#: the LEADING campaign's; below it the campaign is noise and cut («—»). Chosen
#: from the live data: real second campaigns sit at ≥0.145 of the leader (with
#: thousands of ₽ and 100+ clicks), noise seconds at ≤0.022 — a wide empty gap,
#: so 0.10 separates them robustly. Tunable.
_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO = 0.10

#: Minimum Затраты for a campaign-DAY to count as delivering at all; below it
#: the day is cut («—»). Per DAY, not per campaign: the live data shows a real
#: campaign is idle on most of its days (one spending 206 157 ₽ over 63 days,
#: peaking at 10 118 ₽/day, still trickled 3-16 ₽/day for a whole week) — so
#: "is this campaign real?" cannot answer "did it deliver on this day?".
#:
#: Chosen from the live spend distribution of campaign-days (Затраты per
#: campaign x SKU x day, all zones):
#:
#:     <25 ₽      502 days, avg 4-22 Показы    <- residual trickle
#:     25-100 ₽    71 days, avg ~190 Показы
#:     100-200 ₽   19 days, avg ~520 Показы
#:     >=200 ₽    637 days, avg 16 390 Показы  <- real delivery
#:
#: Every noise campaign (one that never delivers on any day) peaks below 200 ₽,
#: so this floor excludes them entirely, while a real campaign's genuinely
#: active days sit far above it — the median active day spends 1 223 ₽, i.e.
#: 10x the floor. WB's own CPM floor (~150-300 ₽ per 1000 Показы) puts 200 ₽ at
#: roughly 700-1300 Показы: about the least a campaign can spend in a day and
#: still be meaningfully in the auction. Tunable.
_MIN_CAMPAIGN_DAY_SPEND = 200.0


def _select_day_buckets(
    campaigns_today: list[tuple[_AdSlice, list[tuple[str, _AdSlice]]]],
    sku_labels: dict[int, str | None] | None = None,
) -> dict[str, MatrixAdBucketBase]:
    """Keep only the significant campaign(s) for a day, cutting the noise.

    A SKU realistically has one — at most two — campaigns actually bringing
    traffic (a paused campaign can still deliver, so status is ignored; only real
    paid delivery counts). A campaign-day must first clear
    :data:`_MIN_CAMPAIGN_DAY_SPEND` to count as delivering at all — a real
    campaign spends thousands of ₽ on the days it runs, so a few ₽ of residual
    trickle is not a campaign the SKU's traffic should be attributed to.
    Survivors are ranked by Показы; the leader is kept, and a second is kept
    only when its Показы are at least
    :data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. Everything else is
    dropped («—»).

    A surviving campaign keeps ALL its zones: a unified campaign's WB search /
    shelves split is shown in full (even a 99/1 split), because that division is
    WB's own. A zone leg with no impressions is omitted (nothing to show).

    Args:
        campaigns_today: One ``(campaign total, zone legs)`` entry per delivering
            campaign that day. A unified campaign's legs are its search + shelves
            slices; a manual campaign's is its single zone.
        sku_labels: Vendor codes for the associative-breakdown rows.

    Returns:
        The surviving ``bucket_key -> input DTO`` map.
    """
    candidates = [
        (total, legs)
        for total, legs in campaigns_today
        if total.views > 0 and total.spend >= _MIN_CAMPAIGN_DAY_SPEND
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
    return {name: _bucket_base(acc, sku_labels) for name, acc in bucket_acc.items()}
