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

from sqlalchemy import CursorResult, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import AdvertisingWriteOffDaily
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("stat_date", "campaign_id", "payment_type", "currency")
_UPDATE = ("amount", "write_offs")


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
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

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
