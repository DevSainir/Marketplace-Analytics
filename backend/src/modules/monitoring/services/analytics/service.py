"""The read-side facade over the analytics sub-services.

:class:`AnalyticsService` keeps the exact constructor and public API the flat
``services/analytics.py`` module exposed (the DI wiring, contract, and routers
are unchanged consumers); each responsibility now lives in its own sub-service
— see the sibling modules for the full method contracts.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.modules.monitoring.repos import (
    AdvertisingRepository,
    AdvertisingSearchRepository,
    CampaignRepository,
    FunnelRepository,
    MatrixOverrideRepository,
    PinnedSkuRepository,
    PriceRepository,
    ProductCardRepository,
    ProductSizeRepository,
    SaleRepository,
    SkuDayActionRepository,
    SkuDayCommentRepository,
    StockRepository,
)
from src.modules.monitoring.schemas import (
    DayActionResponse,
    DayActionState,
    DayCommentResponse,
    FunnelResponseSchema,
    PinnedSkusResponse,
    SkuDetailResponse,
    SkuLookupResponse,
    SkuSummaryListResponse,
    StockRangeResponse,
)
from src.modules.monitoring.schemas.aggregate import AggregateChartsResponse
from src.modules.monitoring.schemas.matrix import (
    MatrixBaseState,
    MatrixCellEdit,
    MatrixPreviewResponse,
)
from src.modules.monitoring.services.analytics.aggregate import AggregateAnalytics
from src.modules.monitoring.services.analytics.annotations import DayAnnotationAnalytics
from src.modules.monitoring.services.analytics.detail import DetailAnalytics
from src.modules.monitoring.services.analytics.matrix_editing import MatrixEditingAnalytics
from src.modules.monitoring.services.analytics.pins import PinnedSkuAnalytics
from src.modules.monitoring.services.analytics.stock_view import StockViewAnalytics
from src.modules.monitoring.services.analytics.summary import SummaryAnalytics


class AnalyticsService:
    """Serves normalized monitoring analytics in summary and detail shapes."""

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
        sale_repo: SaleRepository,
        pinned_sku_repo: PinnedSkuRepository,
        day_comment_repo: SkuDayCommentRepository,
        day_action_repo: SkuDayActionRepository,
    ) -> None:
        """Wire each sub-service from the injected read repositories."""
        self._aggregate = AggregateAnalytics(
            funnel_repo=funnel_repo,
            advertising_repo=advertising_repo,
            stock_repo=stock_repo,
        )
        self._summary = SummaryAnalytics(
            funnel_repo=funnel_repo,
            advertising_repo=advertising_repo,
            stock_repo=stock_repo,
            price_repo=price_repo,
            sale_repo=sale_repo,
            product_card_repo=product_card_repo,
        )
        self._detail = DetailAnalytics(
            funnel_repo=funnel_repo,
            advertising_repo=advertising_repo,
            advertising_search_repo=advertising_search_repo,
            stock_repo=stock_repo,
            campaign_repo=campaign_repo,
            product_card_repo=product_card_repo,
            product_size_repo=product_size_repo,
            matrix_override_repo=matrix_override_repo,
            price_repo=price_repo,
            day_comment_repo=day_comment_repo,
            day_action_repo=day_action_repo,
        )
        self._matrix_editing = MatrixEditingAnalytics(
            detail=self._detail,
            matrix_override_repo=matrix_override_repo,
        )
        self._pins = PinnedSkuAnalytics(
            pinned_sku_repo=pinned_sku_repo,
            product_card_repo=product_card_repo,
        )
        self._annotations = DayAnnotationAnalytics(
            day_comment_repo=day_comment_repo,
            day_action_repo=day_action_repo,
        )
        self._stock_view = StockViewAnalytics(
            stock_repo=stock_repo,
            product_size_repo=product_size_repo,
        )

    # ------------------------------------------------------------------ #
    # Summary listing + lookup
    # ------------------------------------------------------------------ #
    async def list_workspace_nm_ids(self, *, workspace_id: uuid.UUID) -> list[int]:
        """Delegate to :meth:`SummaryAnalytics.list_workspace_nm_ids`."""
        return await self._summary.list_workspace_nm_ids(workspace_id=workspace_id)

    async def get_summary(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SkuSummaryListResponse:
        """Delegate to :meth:`SummaryAnalytics.get_summary`."""
        return await self._summary.get_summary(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    async def lookup_skus_by_vendor_code(
        self, vendor_code: str, *, workspace_id: uuid.UUID
    ) -> SkuLookupResponse:
        """Delegate to :meth:`SummaryAnalytics.lookup_skus_by_vendor_code`."""
        return await self._summary.lookup_skus_by_vendor_code(
            vendor_code, workspace_id=workspace_id
        )

    # ------------------------------------------------------------------ #
    # Detailed view + raw funnel
    # ------------------------------------------------------------------ #
    async def get_aggregate_charts(
        self,
        *,
        workspace_id: uuid.UUID,
        date_from: date | None = None,
        date_to: date | None = None,
        nm_ids: list[int] | None = None,
    ) -> AggregateChartsResponse:
        """Delegate to :meth:`AggregateAnalytics.get_charts`."""
        return await self._aggregate.get_charts(
            workspace_id=workspace_id,
            date_from=date_from,
            date_to=date_to,
            nm_ids=nm_ids,
        )

    async def get_detail(
        self,
        *,
        nm_id: int,
        date_from: date | None = None,
        date_to: date | None = None,
        campaign_id: int | None = None,
        campaign_status: str | None = None,
    ) -> SkuDetailResponse:
        """Delegate to :meth:`DetailAnalytics.get_detail`."""
        return await self._detail.get_detail(
            nm_id=nm_id,
            date_from=date_from,
            date_to=date_to,
            campaign_id=campaign_id,
            campaign_status=campaign_status,
        )

    async def get_sku_funnel(
        self,
        sku: int,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> FunnelResponseSchema:
        """Delegate to :meth:`DetailAnalytics.get_sku_funnel`."""
        return await self._detail.get_sku_funnel(sku, date_from=date_from, date_to=date_to)

    # ------------------------------------------------------------------ #
    # Matrix editing (preview + save)
    # ------------------------------------------------------------------ #
    def preview_matrix_edit(
        self, base: MatrixBaseState, edit: MatrixCellEdit, *, nm_id: int | None = None
    ) -> MatrixPreviewResponse:
        """Delegate to :meth:`MatrixEditingAnalytics.preview_matrix_edit`."""
        return self._matrix_editing.preview_matrix_edit(base, edit, nm_id=nm_id)

    async def save_matrix(
        self,
        *,
        nm_id: int,
        base: MatrixBaseState,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> SkuDetailResponse:
        """Delegate to :meth:`MatrixEditingAnalytics.save_matrix`."""
        return await self._matrix_editing.save_matrix(
            nm_id=nm_id, base=base, date_from=date_from, date_to=date_to
        )

    # ------------------------------------------------------------------ #
    # Pinned SKUs (global «Закрепить» chips)
    # ------------------------------------------------------------------ #
    async def list_pinned_skus(self, *, workspace_id: uuid.UUID) -> PinnedSkusResponse:
        """Delegate to :meth:`PinnedSkuAnalytics.list_pinned_skus`."""
        return await self._pins.list_pinned_skus(workspace_id=workspace_id)

    async def set_sku_pin(
        self, *, workspace_id: uuid.UUID, nm_id: int, pinned: bool
    ) -> PinnedSkusResponse:
        """Delegate to :meth:`PinnedSkuAnalytics.set_sku_pin`."""
        return await self._pins.set_sku_pin(workspace_id=workspace_id, nm_id=nm_id, pinned=pinned)

    async def reorder_pins(
        self, *, workspace_id: uuid.UUID, nm_ids: list[int]
    ) -> PinnedSkusResponse:
        """Delegate to :meth:`PinnedSkuAnalytics.reorder_pins`."""
        return await self._pins.reorder_pins(workspace_id=workspace_id, nm_ids=nm_ids)

    async def set_sku_color(
        self, *, workspace_id: uuid.UUID, nm_id: int, color: str | None
    ) -> PinnedSkusResponse:
        """Delegate to :meth:`PinnedSkuAnalytics.set_sku_color`."""
        return await self._pins.set_sku_color(workspace_id=workspace_id, nm_id=nm_id, color=color)

    # ------------------------------------------------------------------ #
    # Day annotations («Комментарий» notes + «Действия» answers)
    # ------------------------------------------------------------------ #
    async def set_day_note(
        self,
        *,
        nm_id: int,
        comment_date: date,
        body: str | None = None,
        header: str | None = None,
    ) -> DayCommentResponse:
        """Delegate to :meth:`DayAnnotationAnalytics.set_day_note`."""
        return await self._annotations.set_day_note(
            nm_id=nm_id, comment_date=comment_date, body=body, header=header
        )

    async def carry_day_headers(self, *, source_day: date, target_day: date) -> int:
        """Delegate to :meth:`DayAnnotationAnalytics.carry_day_headers`."""
        return await self._annotations.carry_day_headers(
            source_day=source_day, target_day=target_day
        )

    async def set_day_action(
        self, *, nm_id: int, action_date: date, action: DayActionState
    ) -> DayActionResponse:
        """Delegate to :meth:`DayAnnotationAnalytics.set_day_action`."""
        return await self._annotations.set_day_action(
            nm_id=nm_id, action_date=action_date, action=action
        )

    # ------------------------------------------------------------------ #
    # Stock ribbon + warehouse marks
    # ------------------------------------------------------------------ #
    async def get_stock_range(
        self, *, nm_id: int, date_from: date | None, date_to: date | None
    ) -> StockRangeResponse:
        """Delegate to :meth:`StockViewAnalytics.get_stock_range`."""
        return await self._stock_view.get_stock_range(
            nm_id=nm_id, date_from=date_from, date_to=date_to
        )
