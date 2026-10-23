"""Data access for the campaigns a test's traffic came from.

One table, written by the poller and read by the page. It exists because the
counters name a campaign by id and the page has to name it in words — see
:class:`~..models.campaigns.AbTestCampaign` for why those words are copied in
rather than looked up when the page is rendered.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.ab_tests.models import AbTestCampaign
from src.modules.ab_tests.services.campaigns import CampaignKind

#: What a campaign WB would not name is stored as, and what is never written
#: over a kind the register already knows.
_UNKNOWN_KIND: str = str(CampaignKind.UNKNOWN)


@dataclass(frozen=True)
class CampaignFacts:
    """What one pass knows about one campaign.

    ``name`` and ``kind`` are ``None`` for a campaign WB no longer lists — it
    served the card, its windows are on the page, and this pass simply cannot
    say what it is. That is not the same as «unknown»: the register may already
    hold a real name from the passes before it was archived, and overwriting it
    would destroy the only copy there is.
    """

    campaign_id: int
    name: str | None = None
    kind: str | None = None


class CampaignRepository:
    """The per-test register of campaigns that have served the card."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to the request-scoped session.

        Args:
            session: The request's async SQLAlchemy session.
        """
        self._session = session

    async def remember(
        self, *, test_id: uuid.UUID, seen: Sequence[CampaignFacts], at: datetime
    ) -> None:
        """Record that these campaigns were serving this test's card.

        The name and the kind are refreshed on every pass that knows them: a
        seller renaming a campaign mid-test should see the new name, and the
        old one names nothing they can find in the seller portal. A pass that does
        not know keeps what is stored. ``first_seen_at`` is never touched once
        written — it answers "since when has this ad campaign been taking part".

        Args:
            test_id: Owning test.
            seen: The campaigns this pass read counters from.
            at: This pass's clock.
        """
        if not seen:
            return

        stmt = pg_insert(AbTestCampaign).values(
            [
                {
                    "test_id": test_id,
                    "campaign_id": facts.campaign_id,
                    "name": (facts.name or "")[:512],
                    "kind": facts.kind or _UNKNOWN_KIND,
                    "first_seen_at": at,
                    "last_seen_at": at,
                }
                for facts in seen
            ]
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AbTestCampaign.test_id, AbTestCampaign.campaign_id],
                set_={
                    # NULLIF/COALESCE rather than a plain assignment: a pass
                    # with nothing to say must not blank a name it cannot see.
                    "name": func.coalesce(func.nullif(stmt.excluded.name, ""), AbTestCampaign.name),
                    "kind": func.coalesce(
                        func.nullif(stmt.excluded.kind, _UNKNOWN_KIND), AbTestCampaign.kind
                    ),
                    "last_seen_at": stmt.excluded.last_seen_at,
                },
            )
        )
        await self._session.flush()

    async def for_test(self, *, test_id: uuid.UUID) -> list[AbTestCampaign]:
        """Every campaign this test has ever read counters from.

        Args:
            test_id: Owning test.

        Returns:
            The rows, oldest first. A campaign switched off mid-test is still
            here, because the windows it paid for are still on the page.
        """
        stmt = (
            select(AbTestCampaign)
            .where(AbTestCampaign.test_id == test_id)
            .order_by(AbTestCampaign.first_seen_at, AbTestCampaign.campaign_id)
        )
        return list((await self._session.execute(stmt)).scalars().all())


__all__ = ["CampaignFacts", "CampaignRepository"]
