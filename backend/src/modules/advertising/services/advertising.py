"""The «Реклама» read service: load from two contracts, hand to :mod:`.compose`.

Advertising comes from monitoring (WB's ``fullstats``, the search slice, the
funding ledger, the campaign settings); sales come from the finreports
settlement. Nothing here does arithmetic beyond choosing the currency — that is
``compose``'s, and pure.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.timeutils import moscow_today
from src.modules.advertising.schemas import AdvertisingResponse, AdvertisingSpan
from src.modules.advertising.services.compose import SaleDay, compose
from src.modules.finreports.contract import PnlService, SkuReportService
from src.modules.monitoring.contract import (
    ad_coverage,
    funnel_coverage,
    load_ad_campaign_facts,
    load_orders_by_nm,
    load_workspace_catalog,
)


class AdvertisingService:
    """Builds the «Реклама» page for a кабинет and window."""

    def __init__(self, *, pnl: PnlService, skus: SkuReportService) -> None:
        """Wire the read service from the finreports services it takes sales from."""
        self._pnl = pnl
        self._skus = skus

    async def span(self, session: AsyncSession, *, workspace_id: uuid.UUID) -> AdvertisingSpan:
        """Return the days the кабинет has advertising for, and where sales stop.

        The picker's range is the ADVERTISING span, not the settlement's: the
        page is about spend, which lands every day, while the settlement is
        weekly and days late. ``settled_to`` travels beside it so the ДРР line
        can stop where the money does.
        """
        horizon = {"date_from": date(2000, 1, 1), "date_to": moscow_today()}
        first, last = await ad_coverage(session, workspace_id=workspace_id, **horizon)
        settled = await self._pnl.get_settled_span(workspace_id=workspace_id)
        return AdvertisingSpan(
            date_from=first, date_to=last, settled_to=settled[1] if settled else None
        )

    async def build(
        self, session: AsyncSession, *, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> AdvertisingResponse:
        """Return every figure the page draws for one window.

        ДРР is «от продаж» in the strict sense: the seller's own spend — WB's
        bonus taken off — on the settled days, over the settled sales of the
        SAME days (minus returns, at the seller's price, the base the P&L takes
        every share of). Days past the settlement have spend and no sales, and
        are left out of the ratio rather than divided by nothing.
        """
        facts = await load_ad_campaign_facts(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        ad_currencies = list(facts.currencies)

        settled = await self._pnl.get_settled_span(workspace_id=workspace_id)
        settled_to = min(settled[1], date_to) if settled and settled[1] >= date_from else None
        # The lean cut: sales alone. The full SKU-day cut builds forty columns
        # and a cost per cell and was most of this page's load time over a
        # long window (1.2 s of 2.1 s on «Демо»'s whole history).
        sales = (
            [
                SaleDay(cell.nm_id, cell.day, cell.revenue_seller)
                for cell in await self._skus.get_sku_day_sales(
                    workspace_id=workspace_id, date_from=date_from, date_to=settled_to
                )
            ]
            if settled_to is not None
            else []
        )
        currency = await self._pnl.settlement_currency(workspace_id=workspace_id)

        funnel_first, _ = await funnel_coverage(
            session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
        )
        orders = (
            await load_orders_by_nm(
                session, workspace_id=workspace_id, date_from=date_from, date_to=date_to
            )
            if funnel_first
            else None
        )
        catalog = await load_workspace_catalog(session, workspace_id=workspace_id)

        composed = compose(
            facts, sales=sales, settled_to=settled_to, catalog=catalog, orders=orders
        )
        return AdvertisingResponse(
            date_from=date_from,
            date_to=date_to,
            settled_to=settled_to,
            currency=currency or (ad_currencies[0] if len(ad_currencies) == 1 else ""),
            ad_currencies=ad_currencies,
            bonus_known=facts.ledger_known,
            totals=composed.totals,
            zones=composed.zones,
            days=composed.days,
            skus=composed.skus,
        )
