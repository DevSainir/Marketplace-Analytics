"""Classify campaign-days into display-zone buckets and keep the significant ones.

Campaign classification (via the ``Campaign`` dimension's adverts-v2 fields):

* ``manual`` bid + only the SHELVES placement -> the campaign's whole totals
  go to «Руч. полки».
* ``manual`` bid + only the SEARCH placement -> WB's search campaigns also
  deliver in the CATALOG zone (verified against WB's data: fullstats runs ~10-13% above the
  normquery sum), so the search slice goes to «Руч. поиск» and the remainder
  to «Руч. каталог». Without a harvested search slice (legacy rows) the whole
  day stays in «Руч. поиск» — misattributing ~90% of a search campaign to
  catalog would be worse than the old single-zone view.
* ``unified`` bid (always both zones) or a dual-placement manual campaign ->
  split: the search slice goes to the «Поиск» column, the remainder
  (``fullstats - search``, clamped at zero) to «Полки».

A ``cpc`` payment type overrides all of it: WB bills those campaigns per CLICK
rather than per 1000 views, so their bids, their CPM and their «Доля
трафика» share nothing with a CPM campaign's and belong in their own «CPC»
group («Поиск» | «Полки»), whatever the bid type says. A dual-placement CPC
campaign splits on the same normquery slice; a single-placement one keeps its
whole day in the zone it runs in — including a search-only one, which unlike
«Руч. поиск» does NOT shed a catalog remainder, because the CPC group has no
«Каталог» column to put it in and dropping the leg would understate «Общая».

Significant-campaign selection (see :func:`_select_day_buckets`): a SKU
realistically has one — at most two — campaigns actually bringing traffic. A
campaign-day must first spend at least :data:`_MIN_CAMPAIGN_DAY_SPEND` to count
as delivering (:data:`_MIN_CPC_CAMPAIGN_DAY_SPEND` for a pay-per-click campaign,
which buys the same delivery for a quarter of the money); of those, only the
leading campaign (by views) is kept, plus a second campaign when its views clear
:data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. A surviving campaign
keeps ALL its zones (a unified campaign's WB search/shelves split is shown even
at 99/1). Cut campaigns are excluded from «Общая»/«Органика» too.
"""

from __future__ import annotations

from src.modules.monitoring.models import AdvertisingSearchStatDaily, Campaign
from src.modules.monitoring.repos.advertising import CampaignSearchDayTotal
from src.modules.monitoring.schemas.matrix import (
    AssocSkuCount,
    MatrixAdBucketBase,
    MatrixAdSkuBase,
)
from src.modules.monitoring.services.matrix.assoc import _allocate_assoc, _split_assoc_skus
from src.modules.monitoring.services.matrix.slices import _AdSlice, _BucketAcc, _SkuSlice


def _split_sku(
    sku: _SkuSlice, search: AdvertisingSearchStatDaily | None
) -> tuple[_SkuSlice, _SkuSlice]:
    """Split the viewed card's own slice into (search, remainder) by its own row.

    The campaign's zone split is driven by the campaign's search totals; the
    card's own share rides the SAME split but off its OWN normquery row, so
    «Общая»/«Органика» stay the card's whatever the rest of the campaign did.
    Each metric is clamped at the card's own total (the two feeds are collected
    at different times) and the remainder leg takes what is left.
    """
    if search is None:
        return _SkuSlice(), _SkuSlice(**vars(sku))
    taken = _SkuSlice(
        views=min(search.views, sku.views),
        clicks=min(search.clicks, sku.clicks),
        add_to_cart=min(search.add_to_cart, sku.add_to_cart),
        spend=min(float(search.spend), sku.spend),
        orders=min(search.orders, sku.orders),
    )
    rest = _SkuSlice(
        views=sku.views - taken.views,
        clicks=sku.clicks - taken.clicks,
        add_to_cart=sku.add_to_cart - taken.add_to_cart,
        spend=round(sku.spend - taken.spend, 2),
        orders=sku.orders - taken.orders,
    )
    return taken, rest


def _split_search(
    total: _AdSlice,
    search: CampaignSearchDayTotal | None,
    sku_search: AdvertisingSearchStatDaily | None = None,
    viewed_nm: int | None = None,
) -> tuple[_AdSlice, _AdSlice]:
    """Split a dual-zone campaign-day into (search, shelves) slices.

    Both sides are the whole campaign's. The search slice is clamped per-metric
    at the campaign total (the two sources are collected at different times, so
    tiny attribution drifts can put a click in one report before the other); the
    shelves slice is the remainder. Zone-attributed order revenue does not
    exist: both slices carry ``order_sum=None`` unless the campaign-day had no
    revenue at all.

    The conversion split runs against the TRAFFIC-attributed counts, because
    that is all WB's normquery feed reports; the associative extra on top has no
    zone of its own and is apportioned (see :func:`_allocate_assoc`). The viewed
    card's own slice splits alongside, off its own search row.
    """
    s_views = min(search.views, total.views) if search else 0
    s_clicks = min(search.clicks, total.clicks) if search else 0
    s_atbs = min(search.add_to_cart, total.traffic_add_to_cart) if search else 0
    s_spend = min(float(search.spend), total.spend) if search else 0.0
    s_orders = min(search.orders, total.traffic_orders) if search else 0
    revenue: float | None = 0.0 if not total.order_sum else None
    view_share = s_views / total.views if total.views > 0 else 0.0
    extra_carts = max(0, total.add_to_cart - total.traffic_add_to_cart)
    extra_orders = max(0, total.orders - total.traffic_orders)
    s_extra_carts = _allocate_assoc(extra_carts, s_atbs, total.traffic_add_to_cart, view_share)
    s_extra_orders = _allocate_assoc(extra_orders, s_orders, total.traffic_orders, view_share)
    # The associated variants' counts are apportioned — EXCEPT when a zone took
    # none of the extra (or all of it), where the division is forced and the
    # per-variant rows are as exact as the campaign-day's own.
    exact = s_extra_carts in (0, extra_carts) and s_extra_orders in (0, extra_orders)
    sku_search_slice, sku_rest_slice = _split_sku(total.sku, sku_search)
    if viewed_nm is None:
        search_skus: dict[int, tuple[int, int]] = {}
        rest_skus: dict[int, tuple[int, int]] = {}
    else:
        search_skus, rest_skus = _split_assoc_skus(
            total.assoc_skus,
            viewed_nm=viewed_nm,
            search_own=(sku_search_slice.add_to_cart, sku_search_slice.orders),
            search_extra=(s_extra_carts, s_extra_orders),
        )
    search_slice = _AdSlice(
        views=s_views,
        clicks=s_clicks,
        add_to_cart=s_atbs + s_extra_carts,
        spend=s_spend,
        orders=s_orders + s_extra_orders,
        order_sum=revenue,
        traffic_add_to_cart=s_atbs,
        traffic_orders=s_orders,
        sku=sku_search_slice,
        assoc_skus=search_skus,
        assoc_exact=exact,
        currency=total.currency,
    )
    shelves_slice = _AdSlice(
        views=total.views - s_views,
        clicks=total.clicks - s_clicks,
        add_to_cart=(total.traffic_add_to_cart - s_atbs) + (extra_carts - s_extra_carts),
        spend=round(total.spend - s_spend, 2),
        orders=(total.traffic_orders - s_orders) + (extra_orders - s_extra_orders),
        order_sum=revenue,
        traffic_add_to_cart=total.traffic_add_to_cart - s_atbs,
        traffic_orders=total.traffic_orders - s_orders,
        sku=sku_rest_slice,
        assoc_skus=rest_skus,
        assoc_exact=exact,
        currency=total.currency,
    )
    return search_slice, shelves_slice


def _classify(
    meta: Campaign | None,
    total: _AdSlice,
    search: CampaignSearchDayTotal | None,
    sku_search: AdvertisingSearchStatDaily | None = None,
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
    if meta.payment_type == "cpc":
        # Paid per click, so it is never comparable to the CPM columns beside
        # it: own group, same two zones. A search-only CPC campaign keeps its
        # whole day (there is no «CPC · Каталог» column for a remainder).
        if in_search and in_shelves:
            search_slice, shelves_slice = _split_search(total, search, sku_search, viewed_nm)
            return [("cpc_search", search_slice), ("cpc_shelves", shelves_slice)]
        if in_shelves:
            return [("cpc_shelves", total)]
        return [("cpc_search", total)]
    if in_search and in_shelves:
        search_slice, shelves_slice = _split_search(total, search, sku_search, viewed_nm)
        if unified:
            return [("uni_search", search_slice), ("uni_shelves", shelves_slice)]
        return [("manual_search", search_slice), ("manual_shelves", shelves_slice)]
    if unified:
        # Defensive: unified campaigns seen so far always run in both zones, but obey
        # the flags if WB ever ships a single-zone unified campaign.
        return [("uni_search" if in_search else "uni_shelves", total)]
    if in_search:
        # WB's search campaigns also deliver in the CATALOG zone: the
        # normquery slice is «Поиск», the remainder «Каталог». Without a
        # harvested slice for this campaign-day (legacy rows), keep the whole
        # day in «Руч. поиск» — a missing slice must not shove ~90% of a
        # search campaign into catalog.
        if search is None:
            return [("manual_search", total)]
        search_slice, catalog_slice = _split_search(total, search, sku_search, viewed_nm)
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
    acc: _AdSlice | _BucketAcc,
    sku_labels: dict[int, str | None] | None = None,
    campaign_id: int | None = None,
) -> MatrixAdBucketBase:
    """Freeze an ad slice / bucket accumulator into a serializable input DTO."""
    return MatrixAdBucketBase(
        campaign_id=campaign_id,
        views=acc.views,
        clicks=acc.clicks,
        add_to_cart=acc.add_to_cart,
        spend=round(acc.spend, 2),
        orders=acc.orders,
        order_sum=None if acc.order_sum is None else round(acc.order_sum, 2),
        currencies=sorted(acc.currencies) if isinstance(acc, _BucketAcc) else [acc.currency],
        sku=MatrixAdSkuBase(
            views=acc.sku.views,
            clicks=acc.sku.clicks,
            add_to_cart=acc.sku.add_to_cart,
            spend=round(acc.sku.spend, 2),
            orders=acc.sku.orders,
        ),
        assoc_skus=_assoc_sku_counts(acc, sku_labels),
        assoc_exact=acc.assoc_exact,
    )


#: A second campaign is kept only when its views are at least this fraction of
#: the LEADING campaign's; below it the campaign is noise and cut («—»). Chosen
#: from observed data: genuine second campaigns sat at ≥0.145 of the leader (with
#: real spend and 100+ clicks), noise seconds at ≤0.022 — a wide empty gap, so
#: 0.10 separates them robustly. Tunable.
_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO = 0.10

#: Minimum spend for a campaign-DAY to count as delivering at all; below it
#: the day is cut («—»). Per DAY, not per campaign: in observed data a genuine
#: campaign is idle on most of its days (a large one, spending thousands of ₽ a
#: day at its peak, still trickled a few ₽ a day for a whole week) — so "is this
#: campaign real?" cannot answer "did it deliver on this day?".
#:
#: Chosen from the observed spend distribution of campaign-days (spend per
#: campaign x SKU x day, all zones): the days under 25 ₽ are a residual trickle
#: of a few dozen views at most, the 25-200 ₽ band is thin, and the days at
#: 200 ₽ and above carry thousands of views — real delivery.
#:
#: Every noise campaign (one that never delivers on any day) peaks below 200 ₽,
#: so this floor excludes them entirely, while a genuine campaign's active days
#: sit far above it — the median active day spends about 10x the floor. WB's
#: own CPM floor (~150-300 ₽ per 1000 views) puts 200 ₽ at roughly 700-1300
#: views: about the least a campaign can spend in a day and still be
#: meaningfully in the auction. Tunable.
_MIN_CAMPAIGN_DAY_SPEND = 200.0

#: The same floor for a PAY-PER-CLICK campaign, which buys the same delivery for
#: a fraction of the money and would otherwise be cut as trickle on days it
#: plainly ran. Derived, not picked: the floor is a proxy for "did this campaign
#: deliver", and in observed data a CPC campaign's views cost about a quarter of
#: a CPM campaign's (a CPC and a manual campaign compared on the same card and
#: day), so the same bar converts to ~50 ₽.
#:
#: Observed CPC campaign-day-cards separate even more sharply than the CPM ones
#: did, because WB bills these per click and a day with no clicks costs nothing:
#: the days that never delivered cost 0 ₽ with a handful of views and no clicks,
#: while every delivering day cost well over 150 ₽ with hundreds of views and
#: dozens of clicks or more — an empty band above zero, so 50 ₽ separates them
#: with room on both sides. Without it a plainly delivering CPC day read as noise
#: and the «CPC» column stayed blank on that card.
#: Tunable.
_MIN_CPC_CAMPAIGN_DAY_SPEND = 50.0


def _day_spend_floor(legs: list[tuple[str, _AdSlice]]) -> float:
    """The delivery floor a campaign-day must clear, by how WB bills it.

    Read off the legs the campaign was classified into rather than passed in
    separately: a campaign is in the «CPC» buckets exactly when its
    ``payment_type`` put it there, so the classification already carries the
    answer.
    """
    if any(bucket.startswith("cpc_") for bucket, _ in legs):
        return _MIN_CPC_CAMPAIGN_DAY_SPEND
    return _MIN_CAMPAIGN_DAY_SPEND


def _select_day_buckets(
    campaigns_today: list[tuple[_AdSlice, list[tuple[str, _AdSlice]]]],
    sku_labels: dict[int, str | None] | None = None,
) -> dict[str, MatrixAdBucketBase]:
    """Keep only the significant campaign(s) for a day, cutting the noise.

    A SKU realistically has one — at most two — campaigns actually bringing
    traffic (a paused campaign can still deliver, so status is ignored; only actual
    paid delivery counts). A campaign-day must first clear
    :data:`_MIN_CAMPAIGN_DAY_SPEND` ON THIS CARD to count as delivering at all — a real
    campaign spends thousands of ₽ on the days it runs, so a few ₽ of residual
    trickle is not a campaign the SKU's traffic should be attributed to.
    Survivors are ranked by views; the leader is kept, and a second is kept
    only when its views are at least
    :data:`_SECONDARY_MIN_CAMPAIGN_VIEW_RATIO` of the leader's. Everything else is
    dropped («—»).

    A surviving campaign keeps ALL its zones: a unified campaign's WB search /
    shelves split is shown in full (even a 99/1 split), because that division is
    WB's own. A zone leg the card had no impressions in is omitted.

    Args:
        campaigns_today: One ``(campaign total, zone legs)`` entry per delivering
            campaign that day. A unified campaign's legs are its search + shelves
            slices; a manual campaign's is its single zone.
        sku_labels: Vendor codes for the associative-breakdown rows.

    Returns:
        The surviving ``bucket_key -> input DTO`` map.
    """
    # Selection reads the CARD's own delivery, never the campaign's. A campaign
    # promoting a sibling variant books associated conversions here with no
    # traffic and no spend of its own (seen in practice: a card carrying a couple of
    # orders from a campaign whose whole spend went to another card) — its column
    # belongs on the card it advertises, not on this one, and ranked by campaign
    # views it would out-rank the campaign that actually runs here. What the
    # surviving column then SHOWS is the whole campaign; what puts it on this page
    # is the card's own share of it.
    candidates = [
        (total, legs)
        for total, legs in campaigns_today
        if total.sku.views > 0 and total.sku.spend >= _day_spend_floor(legs)
    ]
    candidates.sort(key=lambda entry: entry[0].sku.views, reverse=True)
    if not candidates:
        return {}

    kept = [candidates[0]]
    leader_views = candidates[0][0].sku.views
    if len(candidates) > 1 and (
        candidates[1][0].sku.views >= _SECONDARY_MIN_CAMPAIGN_VIEW_RATIO * leader_views
    ):
        kept.append(candidates[1])

    bucket_acc: dict[str, _BucketAcc] = {}
    # The campaign behind each bucket, for the header's link to it. Two kept
    # campaigns land in one bucket only when both are of one type; the leader
    # (added first) is the one the column is about.
    bucket_campaign: dict[str, int | None] = {}
    for total, legs in kept:
        for bucket_key, slice_ in legs:
            if slice_.sku.views <= 0:
                continue  # the card had no impressions in this zone
            bucket_acc.setdefault(bucket_key, _BucketAcc()).add(slice_)
            bucket_campaign.setdefault(bucket_key, total.campaign_id)
    return {
        name: _bucket_base(acc, sku_labels, bucket_campaign.get(name))
        for name, acc in bucket_acc.items()
    }
