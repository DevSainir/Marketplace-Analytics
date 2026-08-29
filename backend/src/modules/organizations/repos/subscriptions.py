"""Data access for subscription rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import Subscription


class SubscriptionRepository:
    """CRUD operations for :class:`Subscription` rows."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def get_for_organization(self, organization_id: uuid.UUID) -> Subscription | None:
        """Return an organisation's subscription, or ``None`` if it has none.

        ``None`` should not happen for a live tenant — activation creates the
        row in the same transaction as the organisation — but it is modelled as
        possible rather than asserted away, because the caller that has to
        handle it (the access gate) must fail CLOSED on a missing row rather
        than raise a 500 on every request the tenant makes.
        """
        stmt = select(Subscription).where(Subscription.organization_id == organization_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        started_at: datetime,
        expires_at: datetime,
        grace_days: int,
        max_workspaces: int | None = None,
        max_managers: int | None = None,
    ) -> Subscription:
        """Insert and flush a new subscription term.

        Args:
            organization_id: The organisation it governs.
            started_at: Term start (UTC).
            expires_at: Term end (UTC).
            grace_days: Days of full access past ``expires_at``.
            max_workspaces: Workspace cap; ``None`` = unlimited.
            max_managers: Manager cap; ``None`` = unlimited.

        Returns:
            The persisted :class:`Subscription`.
        """
        subscription = Subscription(
            organization_id=organization_id,
            started_at=started_at,
            expires_at=expires_at,
            grace_days=grace_days,
            max_workspaces=max_workspaces,
            max_managers=max_managers,
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def extend(self, subscription: Subscription, *, expires_at: datetime) -> Subscription:
        """Push a term's expiry out to a new date (a renewal).

        ``started_at`` is deliberately left alone: it records when this customer
        first bought, which is what tells us how long they have been with us.
        A renewal moves the end, not the beginning.
        """
        subscription.expires_at = expires_at
        await self._session.flush()
        return subscription
