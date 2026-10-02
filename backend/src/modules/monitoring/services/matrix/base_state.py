"""Aggregate raw fact rows into the editable matrix input working copy.

The first of the two matrix stages: campaign classification, the unified
search/shelves split, and the lagged buyout window all happen here, and the
result is frozen into per-day input facts (:class:`MatrixBaseState`). The
second stage (:func:`~src.modules.monitoring.services.matrix.build.build_matrix_from_base`)
derives the display matrix from it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos.ad_money import RateBook
from src.modules.monitoring.repos.advertising import (
    CampaignDaySkuTotal,
    CampaignDayTotal,
    CampaignSearchDayTotal,
)
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas.matrix import (
    MatrixAdBucketBase,
    MatrixBaseState,
    MatrixDayBase,
    MatrixFunnelBase,
)
from src.modules.monitoring.services.matrix.classification import _classify, _select_day_buckets
from src.modules.monitoring.services.matrix.pricing import _stock_for_day, price_for_day
from src.modules.monitoring.services.matrix.slices import _AdSlice, _day_range, _percent

#: «Процент выкупа» is WB's definition — ``buyouts / DECIDED deliveries``, where
#: a decided delivery is one the buyer either bought out or refused
#: (``buyout_count + cancel_count``) — aggregated over a lagged cohort window:
#: recent order cohorts are still maturing (their deliveries take 1-3 weeks to
#: be accepted or refused), so for a day D the window is ``[D - 21, D - 7]``
#: (e.g. for 10 July: 19 June .. 03 July).
BUYOUT_LAG_START_DAYS = 21
BUYOUT_LAG_END_DAYS = 7


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
    campaign_search_totals: list[CampaignSearchDayTotal] | None = None,
    campaign_sku_totals: list[CampaignDaySkuTotal] | None = None,
    sku_labels: dict[int, str | None] | None = None,
    nm_id: int | None = None,
    price_currency: str = "",
    rates: RateBook | None = None,
) -> MatrixBaseState:
    """Aggregate raw facts into the editable input working copy.

    This is the first of the two matrix stages: it does all the campaign
    classification, the unified search/shelves split, and the lagged buyout
    window, then freezes the result into the per-day input facts. The second
    stage (``build_matrix_from_base``) derives the display matrix from it.
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
        campaign_totals: Per-(campaign, day) metrics across ALL nm_ids — the
            кампания itself, which is what the advertising columns are built
            from. A campaign-day missing from here falls back to the viewed
            card's own rows standing in for the whole campaign.
        campaign_search_totals: The search-zone slice of those same totals,
            campaign-grain. Same fallback: the card's own normquery row.
        campaign_sku_totals: Those same totals broken down per nm_id — the
            hover naming which variants they were booked on. Survives to the
            cell only for campaign-days that were not split across zones.
        sku_labels: Vendor codes keyed by ``nm_id``, for labelling the hover
            rows; an unsynced variant falls back to its raw ``nm_id``.
        nm_id: The SKU being analyzed. Splitting a campaign-day across zones
            needs it to keep the viewed SKU's own counts exact; without it a
            split cell ships no breakdown.
        price_currency: What the prices are stated in — the currency of the
            order money on a day WB served no funnel sum for and ``rates``
            cannot convert.
        rates: The Bank rates into the кабинет's currency (``rates.currency``):
            a day WB served no funnel sum for values its orders at the seller
            price converted at the day's rate, as WB itself would have.

    Returns:
        The :class:`MatrixBaseState` working copy for the window.
    """
    days = _day_range(date_from, date_to)
    funnel_by_date = {row.stat_date: row for row in funnel_rows}
    ordered_prices = sorted(price_snapshots or [], key=lambda s: s.stat_date)
    ordered_stock = sorted(stock_daily or [], key=lambda s: s.stat_date)

    # One slice per (campaign, day) — the WHOLE кампания, which is what an
    # advertising column measures.
    campaign_day: dict[tuple[int, date], _AdSlice] = {
        (total.campaign_id, total.stat_date): _AdSlice(
            views=total.views,
            clicks=total.clicks,
            add_to_cart=total.add_to_cart,
            spend=total.spend,
            orders=total.orders,
            order_sum=total.order_sum,
            traffic_add_to_cart=total.traffic_add_to_cart,
            traffic_orders=total.traffic_orders,
            currency=total.currency,
        )
        for total in campaign_totals or []
    }

    # The viewed card's own share of each campaign-day, aggregated across
    # platforms — «Общая»/«Органика» are built from this, and the carts/orders
    # hover reports the rest of the campaign as the associated share.
    for row in ad_rows:
        key = (row.campaign_id, row.stat_date)
        total = campaign_day.get(key)
        if total is None:
            # No campaign-grain totals for this campaign-day (an older caller,
            # or a totals query that came back short): the card's own rows are
            # the best statement of the campaign available, so it stands in as
            # the whole — which is exactly true for the single-card campaigns
            # this account runs.
            total = campaign_day.setdefault(key, _AdSlice(order_sum=0.0))
            total.views += row.views
            total.clicks += row.clicks
            total.add_to_cart += row.add_to_cart
            total.traffic_add_to_cart += row.add_to_cart
            total.spend += float(row.spend)
            total.orders += row.orders
            total.traffic_orders += row.orders
            if total.order_sum is not None:
                total.order_sum += float(row.order_sum)
        # The card's own rows name the campaign's currency when the campaign's
        # totals did not (a stand-in, or totals harvested before the label).
        total.currency = total.currency or row.currency or ""
        total.sku.views += row.views
        total.sku.clicks += row.clicks
        total.sku.add_to_cart += row.add_to_cart
        total.sku.spend += float(row.spend)
        total.sku.orders += row.orders

    # Stamp the per-variant decomposition of each campaign-day's conversions
    # (the carts/orders hover). The campaign's own counts are clamped from below
    # at the card's own: a partial totals fetch must never leave a campaign
    # holding less than one of its parts, which would drive «Органика» negative.
    skus_by_key: dict[tuple[int, date], dict[int, tuple[int, int]]] = defaultdict(dict)
    for sku_total in campaign_sku_totals or []:
        skus_by_key[(sku_total.campaign_id, sku_total.stat_date)][sku_total.nm_id] = (
            sku_total.add_to_cart,
            sku_total.orders,
        )
    for key, total in campaign_day.items():
        total.views = max(total.views, total.sku.views)
        total.clicks = max(total.clicks, total.sku.clicks)
        total.add_to_cart = max(total.add_to_cart, total.sku.add_to_cart)
        total.traffic_add_to_cart = max(total.traffic_add_to_cart, total.sku.add_to_cart)
        total.spend = max(total.spend, total.sku.spend)
        total.orders = max(total.orders, total.sku.orders)
        total.traffic_orders = max(total.traffic_orders, total.sku.orders)
        total.assoc_skus = skus_by_key.get(key, {})
        total.campaign_id = key[0]

    search_by_key = {(t.campaign_id, t.stat_date): t for t in campaign_search_totals or []}
    sku_search_by_key = {(row.campaign_id, row.stat_date): row for row in search_rows}
    for key, sku_row in sku_search_by_key.items():
        # The same stand-in rule: with no campaign-grain search slice for a
        # campaign-day, the card's own normquery row states the campaign's
        # search zone. Without this a missing aggregate would put a unified
        # campaign's whole day on the shelves side.
        search_by_key.setdefault(
            key,
            CampaignSearchDayTotal(
                campaign_id=sku_row.campaign_id,
                stat_date=sku_row.stat_date,
                views=sku_row.views,
                clicks=sku_row.clicks,
                add_to_cart=sku_row.add_to_cart,
                spend=float(sku_row.spend),
                orders=sku_row.orders,
            ),
        )

    # Classify each campaign-day into its display-zone leg(s): a manual campaign
    # yields one leg, a dual-zone (unified) campaign a search + a shelves slice.
    # Collected per day (with the campaign total) so the significant campaign(s)
    # can be selected.
    day_campaigns: dict[date, list[tuple[_AdSlice, list[tuple[str, _AdSlice]]]]] = defaultdict(list)
    for (campaign_id, stat_date), total in campaign_day.items():
        legs = _classify(
            campaigns.get(campaign_id),
            total,
            search_by_key.get((campaign_id, stat_date)),
            sku_search_by_key.get((campaign_id, stat_date)),
            nm_id,
        )
        if legs:  # unclassifiable campaigns (no settings) are excluded entirely
            day_campaigns[stat_date].append((total, legs))

    day_bases: list[MatrixDayBase] = []
    for day in days:
        # Keep only the significant campaign(s) (cut insignificant traffic). Cut
        # campaigns are excluded from «Общая»/«Органика» too, so the unclassified
        # remainder is empty and each bid type's «Доля трафика» sums to 100%.
        buckets = _select_day_buckets(day_campaigns.get(day, []), sku_labels)

        funnel_row = funnel_by_date.get(day)
        seller_price, customer_price = price_for_day(ordered_prices, day)
        factor = rates.factor(day) if rates is not None and rates.currency else None
        price_rate = None if factor is None else float(factor)
        cabinet = rates.currency if rates is not None else ""
        if funnel_row is not None:
            funnel_base = MatrixFunnelBase(
                open_count=funnel_row.open_count,
                cart_count=funnel_row.cart_count,
                order_count=funnel_row.order_count,
                seller_price=seller_price,
                customer_price=customer_price,
                order_price=_order_price(funnel_row),
                order_currency=funnel_row.currency or cabinet,
                price_currency=price_currency,
                price_rate=price_rate,
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
                order_currency=cabinet,
                price_currency=price_currency,
                price_rate=price_rate,
            )
        else:
            funnel_base = None

        # «Процент выкупа»: WB's definition — buyouts / DECIDED deliveries —
        # over the lagged [D-21, D-7] cohort window (recent cohorts are still
        # maturing). Both inputs are stored facts from the period-aggregate
        # feed, so the window is a plain sum of counts:
        #
        #     Σ buyout_count / Σ (buyout_count + cancel_count)
        #
        # A cohort with ZERO buyouts still contributes its refusals to the
        # denominator — dropping it (as the earlier `buyout_count / WB percent`
        # reconstruction had to, since WB reports percent 0 for such a day and
        # the denominator was unrecoverable) is what made the metric read far
        # too high: SKU 914394276's 15.07 window held four zero-buyout days
        # worth of refusals, and skipping them printed 41% against WB's 16%.
        #
        # `cancel_count is None` = the cohort pass has not refreshed that day
        # yet; it is skipped rather than read as "no refusals", which would
        # invent a 100% cohort.
        window_start = day - timedelta(days=BUYOUT_LAG_START_DAYS)
        window_end = day - timedelta(days=BUYOUT_LAG_END_DAYS)
        buyouts = 0
        decided = 0
        for funnel_row in funnel_rows:
            if not (window_start <= funnel_row.stat_date <= window_end):
                continue
            if funnel_row.cancel_count is None:
                continue
            buyouts += funnel_row.buyout_count
            decided += funnel_row.buyout_count + funnel_row.cancel_count

        day_bases.append(
            MatrixDayBase(
                day=day,
                has_advertising=bool(buckets),
                buckets=buckets,
                unclassified=MatrixAdBucketBase(),  # cut campaigns are excluded
                funnel=funnel_base,
                lagged_buyout_percent=_percent(buyouts, decided),
                stock=_stock_for_day(ordered_stock, day),
            )
        )

    return MatrixBaseState(days=day_bases)


def _order_price(row: SalesFunnelDaily) -> float | None:
    """What one order was worth by WB's funnel sum; ``None`` without one.

    A day with no orders has no price per order — its order money is zero in
    any currency, and the day falls back to the seller price with the rest.
    """
    if row.order_sum is None or not row.order_count or not row.currency:
        return None
    return float(row.order_sum) / row.order_count
