"""The single-SKU detailed view and the raw funnel read.

Also owns :class:`MatrixInputs` — the fact-row bundle one matrix derivation
consumes — shared with the matrix-editing save path so both derive an
identical fact base.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.core.exceptions import NotFoundError
from src.core.timeutils import moscow_today
from src.modules.monitoring.models import (
    AdvertisingSearchStatDaily,
    AdvertisingStatDaily,
    Campaign,
    PriceSnapshot,
    SalesFunnelDaily,
)
from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SkuDayActionRepository,
    SkuDayCommentRepository,
    StockRepository,
    WarehouseMarkRepository,
)
from src.modules.monitoring.repos.advertising import CampaignDaySkuTotal, CampaignDayTotal
from src.modules.monitoring.repos.stocks import StockDailyTotal
from src.modules.monitoring.schemas import (
    DayActionState,
    DayNote,
    FunnelResponseSchema,
    MetricWindow,
    SkuDetailResponse,
    compute_funnel_totals,
)
from src.modules.monitoring.schemas.matrix import MatrixBaseState
from src.modules.monitoring.services.analytics.presenters import (
    build_campaign_advertising,
    build_stock_detail,
    compute_baseline,
    price_funnel_details,
)
from src.modules.monitoring.services.analytics.window import resolve_window
from src.modules.monitoring.services.matrix import (
    BUYOUT_LAG_START_DAYS,
    build_matrix_from_base,
    derive_base_state,
    overlay_overrides,
)


@dataclass(frozen=True)
class MatrixInputs:
    """The fact rows one matrix derivation consumes (extended funnel window)."""

    funnel_rows: list[SalesFunnelDaily]
    ad_rows: list[AdvertisingStatDaily]
    search_rows: list[AdvertisingSearchStatDaily]
    campaigns: dict[int, Campaign]
    price_snapshots: list[PriceSnapshot]
    stock_daily: list[StockDailyTotal]
    campaign_totals: list[CampaignDayTotal]
    campaign_sku_totals: list[CampaignDaySkuTotal]
    sku_labels: dict[int, str | None]


def derive_fact_base(
    inputs: MatrixInputs, *, nm_id: int, date_from: date, date_to: date
) -> MatrixBaseState:
    """Derive the fact-only matrix working copy from one fetched input bundle."""
    return derive_base_state(
        date_from=date_from,
        date_to=date_to,
        funnel_rows=inputs.funnel_rows,
        ad_rows=inputs.ad_rows,
        search_rows=inputs.search_rows,
        campaigns=inputs.campaigns,
        price_snapshots=inputs.price_snapshots,
        stock_daily=inputs.stock_daily,
        campaign_totals=inputs.campaign_totals,
        campaign_sku_totals=inputs.campaign_sku_totals,
        sku_labels=inputs.sku_labels,
        nm_id=nm_id,
    )


class DetailAnalytics:
    """Serves the single-SKU detailed view and the raw funnel read."""

    def __init__(
        self,
        *,
        funnel_repo: FunnelRepository,
        advertising_repo: AdvertisingRepository,
        advertising_search_repo: AdvertisingSearchRepository,
        stock_repo: StockRepository,
        campaign_repo: CampaignRepository,
        product_card_repo: ProductCardRepository,
        product_size_repo: ProductSizeRepository,
        matrix_override_repo: MatrixOverrideRepository,
        price_repo: PriceRepository,
        warehouse_mark_repo: WarehouseMarkRepository,
        day_comment_repo: SkuDayCommentRepository,
        day_action_repo: SkuDayActionRepository,
    ) -> None:
        """Inject the read repositories the detail view composes over."""
        self._funnel = funnel_repo
        self._advertising = advertising_repo
        self._advertising_search = advertising_search_repo
        self._stocks = stock_repo
        self._campaigns = campaign_repo
        self._product_cards = product_card_repo
        self._product_sizes = product_size_repo
        self._matrix_overrides = matrix_override_repo
        self._prices = price_repo
        self._warehouse_marks = warehouse_mark_repo
        self._day_comments = day_comment_repo
        self._day_actions = day_action_repo

    async def get_detail(
        self,
        *,
        nm_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        campaign_id: int | None = None,
        campaign_status: str | None = None,
    ) -> SkuDetailResponse:
        """Build the full detailed view for a single SKU.

        Advertising is grouped per campaign (each with totals + daily breakdown
        and its campaign status), and can be filtered to a single campaign or to
        campaigns of a given status. Stock is returned as a summary total plus a
        size x warehouse breakdown.

        Args:
            nm_id: WB SKU identifier.
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).
            campaign_id: Optional filter — only this campaign's advertising.
            campaign_status: Optional filter — only campaigns whose normalized
                status matches (e.g. ``active``/``paused``/``completed``).

        Returns:
            A :class:`SkuDetailResponse` combining funnel, per-campaign
            advertising, and stock breakdowns plus the cleansed baseline demand.

        Raises:
            NotFoundError: If the SKU has no data of any kind in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        # The funnel is fetched over an EXTENDED window: the matrix's lagged
        # «Процент выкупа» reads up to BUYOUT_LAG_START_DAYS before the first
        # displayed day. Everything else uses the requested window's slice.
        inputs = await self.fetch_matrix_inputs(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        funnel_rows = [row for row in inputs.funnel_rows if row.stat_date >= date_from]
        # The per-day stock totals feed both the matrix stock/in-transit rows
        # and OOS masking; the latest snapshot's size x warehouse rows feed the
        # breakdown table (filtered in SQL, not hydrated wholesale).
        stock_daily_totals = {total.stat_date: total.quantity for total in inputs.stock_daily}
        latest_stock_rows = await self._stocks.list_latest_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )

        if not funnel_rows and not inputs.ad_rows and not inputs.stock_daily:
            raise NotFoundError(f"No monitoring data found for SKU {nm_id}.")

        # Group + filter the per-campaign advertising view.
        advertising = build_campaign_advertising(inputs.ad_rows, inputs.campaigns)
        if campaign_status is not None:
            advertising = [c for c in advertising if c.status_label == campaign_status]

        # Derive the matrix input working copy, then overlay any manual edits
        # so the served matrix (and the editable base) reflect saved overrides.
        base = derive_fact_base(inputs, nm_id=nm_id, date_from=date_from, date_to=date_to)
        overrides = await self._matrix_overrides.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        overlay_overrides(base, overrides, nm_id=nm_id)

        # The raw funnel list/totals carry the same price-derived ₽ volumes
        # (count x carry-forward seller price) the matrix «Общая» column shows.
        funnel_details, window_order_sum, window_buyout_sum = price_funnel_details(
            funnel_rows, inputs.price_snapshots
        )

        # Decorate identity + sizes from the catalogue dimensions (nullable —
        # a SKU with stock but no synced card still renders, just label-less).
        card = (await self._product_cards.get_by_ids([nm_id])).get(nm_id)
        size_labels = await self._product_sizes.get_labels_by_chrt_ids(
            {row.chrt_id for row in latest_stock_rows}
        )
        marked_warehouses = await self._warehouse_marks.list_names(nm_id=nm_id)
        comment_rows = await self._day_comments.map_for_window(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
        action_rows = await self._day_actions.map_for_window(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )

        return SkuDetailResponse(
            nm_id=nm_id,
            vendor_code=card.vendor_code if card else None,
            title=card.title if card else None,
            comments={
                day: DayNote(body=row.body, header=row.header) for day, row in comment_rows.items()
            },
            day_actions={
                day: DayActionState.model_validate(row, from_attributes=True)
                for day, row in action_rows.items()
            },
            window=MetricWindow(start=date_from, end=date_to),
            funnel=funnel_details,
            funnel_totals=compute_funnel_totals(
                funnel_rows, order_sum=window_order_sum, buyout_sum=window_buyout_sum
            ),
            baseline_demand=compute_baseline(funnel_rows, stock_daily_totals),
            advertising=advertising,
            matrix=build_matrix_from_base(base),
            matrix_base=base,
            stock=build_stock_detail(latest_stock_rows, size_labels, marked_warehouses),
        )

    async def get_sku_funnel(
        self,
        sku: int,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> FunnelResponseSchema:
        """Return the raw organic sales funnel for a single SKU.

        Args:
            sku: WB SKU identifier (``nm_id``).
            date_from: Optional inclusive window start (defaults applied here).
            date_to: Optional inclusive window end (defaults applied here).

        Returns:
            A populated :class:`FunnelResponseSchema` (raw per-day metrics).

        Raises:
            NotFoundError: If the SKU has no funnel data in the window.
        """
        date_from, date_to = resolve_window(date_from, date_to)
        funnel_rows = await self._funnel.list_for_sku(
            nm_id=sku, date_from=date_from, date_to=date_to
        )
        if not funnel_rows:
            raise NotFoundError(f"No funnel metrics found for SKU {sku}.")

        price_snapshots = await self._prices.list_for_sku(
            nm_id=sku, date_from=date_from, date_to=max(date_to, moscow_today())
        )
        funnel_details, window_order_sum, window_buyout_sum = price_funnel_details(
            funnel_rows, price_snapshots
        )
        return FunnelResponseSchema(
            nm_id=sku,
            window_start=date_from,
            window_end=date_to,
            raw_orders=sum(r.order_count for r in funnel_rows),
            totals=compute_funnel_totals(
                funnel_rows, order_sum=window_order_sum, buyout_sum=window_buyout_sum
            ),
            days=funnel_details,
        )

    async def fetch_matrix_inputs(
        self,
        *,
        nm_id: int,
        date_from: date,
        date_to: date,
        campaign_id: int | None = None,
    ) -> MatrixInputs:
        """Fetch the fact rows the matrix is derived from (extended funnel window).

        Shared by the detail read and the save path so both derive an identical
        fact-base. The funnel spans ``[date_from - BUYOUT_LAG_START_DAYS, date_to]``
        for the lagged «Процент выкупа»; price snapshots share that extended
        window so early display days can carry an earlier price forward.
        """
        extended_start = date_from - timedelta(days=BUYOUT_LAG_START_DAYS)
        extended_funnel_rows = await self._funnel.list_for_sku(
            nm_id=nm_id,
            date_from=extended_start,
            date_to=date_to,
        )
        ad_rows = await self._advertising.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        search_rows = await self._advertising_search.list_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
        )
        campaigns = await self._campaigns.get_by_ids({row.campaign_id for row in ad_rows})
        # All-variant conversion totals of the same campaigns — the associative
        # «100» decorating the SKU's own «71» in the matrix carts/orders cells.
        campaign_ids = {row.campaign_id for row in ad_rows}
        campaign_totals = await self._advertising.campaign_day_totals(
            campaign_ids=campaign_ids,
            date_from=date_from,
            date_to=date_to,
        )
        # ...and the same totals per variant, naming who they were booked on
        # (the carts/orders hover). Labelled from the catalogue so the hover can
        # say «M-TRX01-BLK» rather than a bare nm_id.
        campaign_sku_totals = await self._advertising.campaign_day_sku_totals(
            campaign_ids=campaign_ids,
            date_from=date_from,
            date_to=date_to,
        )
        assoc_cards = await self._product_cards.get_by_ids(
            [total.nm_id for total in campaign_sku_totals]
        )
        sku_labels: dict[int, str | None] = {
            nm_id: card.vendor_code for nm_id, card in assoc_cards.items()
        }
        # Prices/stock are snapshotted on the harvest day (Moscow *today*), but
        # the analysis window ends *yesterday* (WB serves no current-day
        # funnel), so the latest snapshot sits just outside [.., date_to]. Reach
        # up to today so carry-forward can apply it to the recent display days.
        snapshot_end = max(date_to, moscow_today())
        price_snapshots = await self._prices.list_for_sku(
            nm_id=nm_id, date_from=extended_start, date_to=snapshot_end
        )
        stock_daily = await self._stocks.daily_totals_for_sku(
            nm_id=nm_id, date_from=date_from, date_to=snapshot_end
        )
        return MatrixInputs(
            funnel_rows=extended_funnel_rows,
            ad_rows=ad_rows,
            search_rows=search_rows,
            campaigns=campaigns,
            price_snapshots=price_snapshots,
            stock_daily=stock_daily,
            campaign_totals=campaign_totals,
            campaign_sku_totals=campaign_sku_totals,
            sku_labels=sku_labels,
        )
