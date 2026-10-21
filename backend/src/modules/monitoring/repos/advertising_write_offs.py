"""Repository for :class:`AdvertisingWriteOffDaily` — who funded the ads.

Kept apart from :mod:`~src.modules.monitoring.repos.advertising` because the two
answer different questions about the same campaigns: that one holds impressions
and the spend they cost, this one holds the charges and the pocket each came
out of. They are also swept differently — see :meth:`delete_window_for_campaigns`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import (
    AdvertisingStatDaily,
    AdvertisingWriteOffDaily,
    ProductCard,
)
from src.modules.monitoring.repos.ad_money import FX_COLUMNS, as_served
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "campaign_id", "payment_type", "currency")
_UPDATE = ("amount", "write_offs", *FX_COLUMNS)


class AdvertisingWriteOffRepository(BaseRepository):
    """CRUD/read operations for daily advertising write-offs."""

    model = AdvertisingWriteOffDaily

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert a batch of write-off buckets.

        Args:
            rows: Column->value mappings keyed by the four-column composite PK.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(
            as_served(rows), conflict_columns=_CONFLICT, update_columns=_UPDATE
        )

    async def delete_window_for_campaigns(
        self, *, date_from: date, date_to: date, campaign_ids: Sequence[int]
    ) -> int:
        """Delete a window's write-offs for the given campaigns.

        Scoped to campaigns rather than to the bare window because the feed is
        served per advertising token: one workspace re-harvesting must never
        sweep another account's rows out of the shared table. The campaigns of
        the payload being ingested are exactly the ones about to be rewritten.

        Args:
            date_from: Inclusive window start.
            date_to: Inclusive window end.
            campaign_ids: Campaigns whose rows may be replaced.

        Returns:
            How many rows were deleted.
        """
        if not campaign_ids:
            return 0
        stmt = delete(AdvertisingWriteOffDaily).where(
            AdvertisingWriteOffDaily.stat_date >= date_from,
            AdvertisingWriteOffDaily.stat_date <= date_to,
            AdvertisingWriteOffDaily.campaign_id.in_(list(campaign_ids)),
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        return result.rowcount or 0

    async def currencies_for_campaigns(
        self, *, campaign_ids: Sequence[int], date_from: date, date_to: date
    ) -> list[str]:
        """Return the currencies these campaigns were charged in over a window.

        The ledger's label is the campaign's own unit, and it is honest: a
        campaign keeps the currency it was created in (the ad account moved
        RUB -> KGS on 2026-08-20, and campaigns made before that still bill in
        RUB), so a window can carry both. Bonus rows count too — they are
        charged in the same unit as the campaign's cash rows, and a campaign
        funded wholly by cashback has no other row to read.

        Args:
            campaign_ids: The campaigns whose spend is being labelled.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            The distinct labels, alphabetically; empty when none were charged.
        """
        if not campaign_ids:
            return []
        stmt = (
            select(AdvertisingWriteOffDaily.currency)
            .where(
                AdvertisingWriteOffDaily.stat_date >= date_from,
                AdvertisingWriteOffDaily.stat_date <= date_to,
                AdvertisingWriteOffDaily.currency != "",
                AdvertisingWriteOffDaily.campaign_id.in_(list(campaign_ids)),
            )
            .group_by(AdvertisingWriteOffDaily.currency)
            .order_by(AdvertisingWriteOffDaily.currency)
        )
        return [str(currency) for currency in (await self._session.execute(stmt)).scalars()]

    async def currencies_for_sku_cabinet(
        self, *, nm_id: int, date_from: date, date_to: date
    ) -> list[str]:
        """Return the currencies the SKU's whole workspace was charged in over a window.

        The fallback for :meth:`currencies_for_campaigns`. The ledger names only
        some campaigns — about a quarter of those that spent in one sampled
        fortnight — so a SKU advertised by the others would print its spend
        with no unit, where the workspace's own label is almost always the right
        one. The workspace is the one owning this SKU's card (``nm_id`` is the
        card's primary key), and only campaigns that advertised its cards count.

        Args:
            nm_id: The SKU whose workspace is being asked about.
            date_from: Inclusive window start.
            date_to: Inclusive window end.

        Returns:
            The distinct labels, alphabetically; empty when none were charged.
        """
        cabinet = select(ProductCard.workspace_id).where(ProductCard.nm_id == nm_id)
        cards = select(ProductCard.nm_id).where(ProductCard.workspace_id.in_(cabinet))
        campaigns = (
            select(AdvertisingStatDaily.campaign_id)
            .where(AdvertisingStatDaily.nm_id.in_(cards))
            .distinct()
        )
        stmt = (
            select(AdvertisingWriteOffDaily.currency)
            .where(
                AdvertisingWriteOffDaily.stat_date >= date_from,
                AdvertisingWriteOffDaily.stat_date <= date_to,
                AdvertisingWriteOffDaily.currency != "",
                AdvertisingWriteOffDaily.campaign_id.in_(campaigns),
            )
            .group_by(AdvertisingWriteOffDaily.currency)
            .order_by(AdvertisingWriteOffDaily.currency)
        )
        return [str(currency) for currency in (await self._session.execute(stmt)).scalars()]
