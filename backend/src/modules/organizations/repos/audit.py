"""Insert-only data access for the audit log.

There is no ``update`` and no ``delete`` here, and that absence is the point of
the file. The database enforces the same thing by grant (see the migration), so
this repository is not the control — it is the shape the control expects, and a
reader who comes looking for the update method should find nothing rather than
find one that "is only used carefully".

Reads live here too, because an audit trail nobody can query is a write-only
log, which is a different and less useful thing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.organizations.models import AuditLogEntry


class AuditLogRepository:
    """Appends to, and reads from, ``organizations.audit_log``."""

    def __init__(self, session: AsyncSession) -> None:
        """Store the injected request-scoped async session."""
        self._session = session

    async def append(
        self,
        *,
        event: str,
        actor_user_id: uuid.UUID | None,
        actor_email: str | None,
        organization_id: uuid.UUID | None,
        target_type: str | None = None,
        target_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogEntry:
        """Write one event.

        Added to the request's session rather than committed here, so the record
        and the thing it describes land in the same transaction: a rolled-back
        action leaves no claim that it happened, and a committed one cannot fail
        to be recorded.

        Args:
            event: An :class:`~src.modules.organizations.models.AuditEvent` value.
            actor_user_id: Who did it, denormalised (no foreign key).
            actor_email: Their address at the time, so the row still names a
                person once the account is gone.
            organization_id: The tenant it happened in, denormalised likewise.
            target_type: What kind of thing it was done to.
            target_id: Which one, as a plain value.
            ip_address: Where from, as resolved by ``src.core.client_ip``.
            user_agent: What with.
            metadata: Which fields changed. **Never a secret value.**

        Returns:
            The pending entry.
        """
        entry = AuditLogEntry(
            event=event,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_=metadata,
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list_for_organization(
        self, organization_id: uuid.UUID, *, limit: int = 200
    ) -> list[AuditLogEntry]:
        """Return the tenant's most recent events, newest first.

        Scoped by ``organization_id`` with no un-scoped variant, because this
        table records who did what inside a customer's company and the one
        mistake worth designing out is showing it to a different customer.

        Args:
            organization_id: The tenant whose trail is being read.
            limit: Hard cap on rows returned.

        Returns:
            Up to ``limit`` entries, newest first.
        """
        stmt = (
            select(AuditLogEntry)
            .where(AuditLogEntry.organization_id == organization_id)
            .order_by(AuditLogEntry.occurred_at.desc(), AuditLogEntry.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["AuditLogRepository"]
