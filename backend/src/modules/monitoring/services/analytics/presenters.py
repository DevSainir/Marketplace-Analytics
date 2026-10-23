"""Pure DTO builders shared by the analytics read services.

Every function here is presentation-shaping over already-fetched rows: no SQL,
no HTTP, no repository access.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
    StockSnapshot,
    normalize_type,
)
from src.modules.monitoring.schemas import (
    BaselineDemandRead,
    CampaignAdvertising,
    CampaignDailyStat,
    FunnelDetailRead,
    StockCell,
    StockDetail,
    StockSizeTotal,
    compute_ad_metrics,
)
from src.modules.monitoring.services.matrix import price_for_day
from src.modules.monitoring.services.normalization import (
    DailyDemandPoint,
    compute_baseline_demand,
)

# Everything the card's day DTO copies from the stored row; the ₽ volumes it derives.
_FUNNEL_ROW_FIELDS = tuple(
    name for name in FunnelDetailRead.model_fields if name not in {"order_sum", "buyout_sum"}
)


def price_funnel_details(
    funnel_rows: list[SalesFunnelDaily],
    price_snapshots: list[PriceSnapshot],
) -> tuple[list[FunnelDetailRead], float, float]:
    """Build per-day funnel DTOs with price-derived ₽ volumes + their window totals.

    The stored funnel row no longer carries ₽ volumes; each day's "Orders, ₽" /
    "Buyouts, ₽" are ``count x carry-forward seller price`` (``0.0`` when the SKU
    is unpriced), matching the matrix "Overall" column.

    Args:
        funnel_rows: The SKU's daily funnel rows for the display window.
        price_snapshots: The SKU's price snapshots (any order).

    Returns:
        ``(day_dtos, window_order_sum, window_buyout_sum)``.
    """
    ordered = sorted(price_snapshots, key=lambda s: s.stat_date)
    details: list[FunnelDetailRead] = []
    total_order_sum = total_buyout_sum = 0.0
    for row in funnel_rows:
        seller, _customer = price_for_day(ordered, row.stat_date)
        # Not ``model_validate(row)``: the row's own ``order_sum``/``buyout_sum``
        # are WB's, in the settlement currency and NULL until backfilled — the
        # card's roubles are the derived ones below, never those.
        detail = FunnelDetailRead(
            **{name: getattr(row, name) for name in _FUNNEL_ROW_FIELDS},
            order_sum=round(row.order_count * seller, 2) if seller is not None else 0.0,
            buyout_sum=round(row.buyout_count * seller, 2) if seller is not None else 0.0,
        )
        total_order_sum += detail.order_sum
        total_buyout_sum += detail.buyout_sum
        details.append(detail)
    return details, round(total_order_sum, 2), round(total_buyout_sum, 2)


def compute_baseline(
    funnel_rows: list[SalesFunnelDaily],
    stock_daily_totals: dict[date, int],
) -> BaselineDemandRead:
    """Run the normalization pipeline over a SKU's window.

    Joins each funnel day with that day's total stock so out-of-stock days are
    masked out of the demand baseline. A day with no stock snapshot at all
    (harvest gap) is treated as in-stock — masking requires positive evidence
    of OOS, otherwise gaps would silently deflate ``considered_days``.

    Promo-lift and seasonality factors stay at their neutral ``1.0`` defaults
    until those data sources are integrated.
    """
    points = [
        DailyDemandPoint(
            day=row.stat_date,
            raw_orders=row.order_count,
            total_stock=stock_daily_totals.get(row.stat_date, 1),
        )
        for row in funnel_rows
    ]
    result = compute_baseline_demand(points)
    return BaselineDemandRead(
        baseline_organic_demand=result.baseline_organic_demand,
        oos_days_excluded=result.oos_days_excluded,
        considered_days=result.considered_days,
    )


def build_campaign_advertising(
    ad_rows: list[AdvertisingStatDaily],
    campaigns: dict[int, Campaign],
) -> list[CampaignAdvertising]:
    """Group flat advertising rows into per-campaign views with totals.

    Args:
        ad_rows: The SKU's advertising rows (already window/campaign filtered).
        campaigns: Campaign metadata keyed by ``campaign_id`` (may be partial).

    Only campaigns that actually **delivered** ads for this SKU in the window
    (views > 0, clicks > 0, or spend > 0) are included — campaigns with merely
    attribution-window orders (0 views/clicks/spend) are dropped as noise.

    Returns:
        One :class:`CampaignAdvertising` per delivering campaign, ordered by
        descending spend, each carrying totals, derived CPM/CTR/CPC, and a
        per-day/platform breakdown.
    """
    by_campaign: dict[int, list[AdvertisingStatDaily]] = defaultdict(list)
    for row in ad_rows:
        by_campaign[row.campaign_id].append(row)

    result: list[CampaignAdvertising] = []
    for campaign_id, rows in by_campaign.items():
        views = sum(r.views for r in rows)
        clicks = sum(r.clicks for r in rows)
        add_to_cart = sum(r.add_to_cart for r in rows)
        spend = float(sum(r.spend for r in rows))
        orders = sum(r.orders for r in rows)
        # Drop campaigns that did not deliver any ads for this SKU.
        if views == 0 and clicks == 0 and spend == 0:
            continue

        meta = campaigns.get(campaign_id)
        result.append(
            CampaignAdvertising(
                campaign_id=campaign_id,
                type=meta.type if meta else None,
                type_label=normalize_type(meta.type) if meta else None,
                status=meta.status if meta else None,
                status_label=meta.status_label if meta else None,
                views=views,
                clicks=clicks,
                add_to_cart=add_to_cart,
                spend=spend,
                orders=orders,
                metrics=compute_ad_metrics(
                    views=views,
                    clicks=clicks,
                    add_to_cart=add_to_cart,
                    spend=spend,
                    orders=orders,
                ),
                daily=[
                    CampaignDailyStat(
                        stat_date=r.stat_date,
                        app_type=r.app_type,
                        views=r.views,
                        clicks=r.clicks,
                        add_to_cart=r.add_to_cart,
                        spend=float(r.spend),
                        orders=r.orders,
                        metrics=compute_ad_metrics(
                            views=r.views,
                            clicks=r.clicks,
                            add_to_cart=r.add_to_cart,
                            spend=float(r.spend),
                            orders=r.orders,
                        ),
                    )
                    for r in rows
                ],
            )
        )
    result.sort(key=lambda c: c.spend, reverse=True)
    return result


def build_stock_detail(
    latest: list[StockSnapshot],
    size_labels: dict[int, str],
) -> StockDetail:
    """Build the stock summary + size x warehouse breakdown for a SKU.

    Receives only the most recent snapshot day's rows (the repository filters
    in SQL — stock is a point-in-time snapshot, not a series). Each ``chrt_id``
    is decorated with its human ``tech_size`` from ``size_labels`` (``None``
    when the catalogue has not been synced for that size yet, so old rows keep
    working).

    Args:
        latest: The SKU's rows for its latest snapshot day in the window.
        size_labels: Map of ``chrt_id -> tech_size`` for the SKU's sizes.

    Returns:
        A populated :class:`StockDetail` (all zeros/empty when no stock exists).
    """
    if not latest:
        return StockDetail(
            total_quantity=0,
            total_in_way_to_client=0,
            total_in_way_from_client=0,
        )

    by_size: dict[int, int] = defaultdict(int)
    for row in latest:
        by_size[row.chrt_id] += row.quantity

    return StockDetail(
        total_quantity=sum(r.quantity for r in latest),
        total_in_way_to_client=sum(r.in_way_to_client for r in latest),
        total_in_way_from_client=sum(r.in_way_from_client for r in latest),
        by_size=[
            StockSizeTotal(
                chrt_id=chrt_id,
                tech_size=size_labels.get(chrt_id),
                quantity=qty,
            )
            for chrt_id, qty in sorted(by_size.items())
        ],
        cells=[
            StockCell(
                chrt_id=r.chrt_id,
                tech_size=size_labels.get(r.chrt_id),
                warehouse_name=r.warehouse_name,
                region_name=r.region_name,
                quantity=r.quantity,
                in_way_to_client=r.in_way_to_client,
                in_way_from_client=r.in_way_from_client,
            )
            for r in latest
        ],
    )
