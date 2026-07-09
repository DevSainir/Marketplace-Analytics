"""Repository for the :class:`Campaign` advertising dimension."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import Campaign
from src.modules.monitoring.repos.base import BaseRepository

_CONFLICT = ("campaign_id",)
_UPDATE = ("type", "status", "status_label", "synced_at")


class CampaignRepository(BaseRepository):
    """CRUD/read operations for advertising campaign metadata."""

    model = Campaign

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session."""
        super().__init__(session)

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        """Idempotently upsert campaign descriptors keyed by ``campaign_id``.

        Args:
            rows: Column->value mappings for each campaign.

        Returns:
            The number of rows submitted.
        """
        return await self.bulk_upsert(rows, conflict_columns=_CONFLICT, update_columns=_UPDATE)

    async def get_by_ids(self, campaign_ids: Iterable[int]) -> dict[int, Campaign]:
        """Return campaign metadata for the given ids, keyed by ``campaign_id``.

        Args:
            campaign_ids: Campaign ids to look up.

        Returns:
            A mapping of ``campaign_id -> Campaign`` (missing ids are omitted).
        """
        ids = list(campaign_ids)
        if not ids:
            return {}
        stmt = select(Campaign).where(Campaign.campaign_id.in_(ids))
        result = await self._session.execute(stmt)
        return {c.campaign_id: c for c in result.scalars().all()}

    async def list_ids_by_status(self, status_labels: Sequence[str]) -> set[int]:
        """Return the ids of campaigns whose normalized status matches.

        Args:
            status_labels: Normalized status labels to include (e.g.
                ``["active", "paused"]``).

        Returns:
            The set of matching campaign ids.
        """
        if not status_labels:
            return set()
        stmt = select(Campaign.campaign_id).where(Campaign.status_label.in_(list(status_labels)))
        result = await self._session.execute(stmt)
        return set(result.scalars().all())
