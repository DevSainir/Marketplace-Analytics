"""Derive the display matrix from an input working copy.

The second matrix stage: pure derivation, no aggregation. Reused verbatim by
the read path (after overlaying overrides) and the preview path (after applying
a pending edit), so every consumer sees identical formulas.
"""

from __future__ import annotations

from datetime import date

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.advertising import CampaignDayTotal, CampaignSearchDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import (
    MATRIX_BUCKETS,
    MATRIX_METRIC_KEYS,
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixDayBase,
    MatrixMetricRow,
    MetricsMatrixRead,
    bucket_traffic_type,
)
from src.modules.monitoring.services.matrix.base_state import derive_base_state
from src.modules.monitoring.services.matrix.cells import (
    _ad_cell,
    _campaign_drr_sales,
    _organic_cell,
    _total_cell,
)
from src.modules.monitoring.services.matrix.slices import _BucketAcc, _SkuSlice


def _acc_from_base(base: MatrixAdBucketBase) -> _BucketAcc:
    """Rehydrate a bucket accumulator from its input DTO."""
    return _BucketAcc(
        views=base.views,
        clicks=base.clicks,
        add_to_cart=base.add_to_cart,
        spend=base.spend,
        orders=base.orders,
        order_sum=base.order_sum,
        sku=_SkuSlice(
            views=base.sku.views,
            clicks=base.sku.clicks,
            add_to_cart=base.sku.add_to_cart,
            spend=base.sku.spend,
            orders=base.sku.orders,
        ),
        assoc_skus={c.nm_id: (c.add_to_cart, c.orders) for c in base.assoc_skus},
        assoc_exact=base.assoc_exact,
    )


def _day_ad_from_base(day: MatrixDayBase) -> _SkuSlice | None:
    """Reconstruct the CARD's own advertising day = Σ its slice of each bucket.

    «Общая» is the viewed card's whole day and «Органика» that day minus what
    the ads brought, so both are built from the card's own share of each
    bucket — never from the campaigns' totals, which for a campaign promoting
    several cards would lend this one the others' spend and drive «Органика»
    negative.

    Returns ``None`` for days with no advertising at all, so «Общая» ad cells
    render «—» exactly as before (a zero accumulator would show ``0``).
    """
    if not day.has_advertising:
        return None
    total = _SkuSlice()
    for base in (*day.buckets.values(), day.unclassified):
        total.views += base.sku.views
        total.clicks += base.sku.clicks
        total.add_to_cart += base.sku.add_to_cart
        total.spend += base.sku.spend
        total.orders += base.sku.orders
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
            # «Доля трафика» is normalized within each «тип получения трафика»
            # (Единая / Ручной / CPC each sum to 100%), so precompute per-type
            # total Показы.
            type_views: dict[str, int] = {}
            for name, b in day.buckets.items():
                traffic_type = bucket_traffic_type(name)
                type_views[traffic_type] = type_views.get(traffic_type, 0) + b.views
            for bucket in MATRIX_BUCKETS:
                if bucket == "total":
                    value = _total_cell(key, day, day_ad)
                elif bucket == "organic":
                    value = _organic_cell(key, day.funnel, day_ad)
                elif key == "drr_sales":
                    # Campaign-level (all zones of the group share one value).
                    value = _campaign_drr_sales(bucket, day, bucket_accs)
                else:
                    bid_views = type_views.get(bucket_traffic_type(bucket), 0)
                    value = _ad_cell(key, bucket_accs.get(bucket), bid_views, day, bucket)
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
    campaign_search_totals: list[CampaignSearchDayTotal] | None = None,
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
        campaign_totals: Per-(campaign, day) metrics across all nm_ids — the
            кампания the advertising columns measure.
        campaign_search_totals: The search-zone slice of those totals.

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
            campaign_search_totals=campaign_search_totals,
        )
    )
