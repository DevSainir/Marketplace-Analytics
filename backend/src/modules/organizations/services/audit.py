"""Recording security-relevant events with the actor already filled in.

The value of an audit trail is decided by how easy it is to write a *correct*
entry at a call site that is busy doing something else. If every caller has to
remember to look up the actor's email, resolve the client address off the
request and pass the tenant, then entries will be written with fields missing —
and a trail that says "somebody removed a member" is barely better than no trail.

So the actor context is resolved once, by the dependency that builds this, and a
call site supplies only what it alone knows: the event, what it was done to, and
what changed.

**Failure policy: never break the action.** An audit write that raised would
mean a manager cannot be removed because the log is unhappy, which trades a real
capability for a record of it. The write is added to the caller's transaction —
so a rolled-back action leaves no claim it happened — but an unexpected failure
is logged loudly and swallowed. That is a deliberate weakening, and it is the
one place this design is softer than "the database enforces it": the enforcement
covers what the trail says once written, not that every event reaches it.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.core.logging import get_logger
from src.modules.organizations.models import AuditEvent, AuditLogEntry
from src.modules.organizations.repos.audit import AuditLogRepository

logger = get_logger(__name__)

#: User-Agent strings run to kilobytes; the column keeps a usable prefix.
_USER_AGENT_LIMIT = 256


class AuditRecorder:
    """Writes audit entries for one request, with its actor already resolved.

    Built per request by :func:`~src.modules.organizations.deps.get_audit_recorder`.

    Args:
        repo: The insert-only audit repository on the request's session.
        actor_user_id: The authenticated caller, or ``None`` for unattended work.
        actor_email: That caller's address at the time.
        organization_id: The tenant the caller is acting in, if any.
        ip_address: Client address as resolved by ``src.core.client_ip``.
        user_agent: Raw User-Agent header; truncated on write.
    """

    def __init__(
        self,
        *,
        repo: AuditLogRepository,
        actor_user_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        organization_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Capture the actor context for every entry this recorder writes."""
        self._repo = repo
        self._actor_user_id = actor_user_id
        self._actor_email = actor_email
        self._organization_id = organization_id
        self._ip_address = ip_address
        self._user_agent = (user_agent or "")[:_USER_AGENT_LIMIT] or None

    async def record(
        self,
        event: AuditEvent,
        *,
        target_type: str | None = None,
        target_id: object = None,
        organization_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record one event, or log why it could not be recorded.

        Args:
            event: What happened.
            target_type: What kind of thing it happened to.
            target_id: Which one; stringified, so a UUID or an int both work.
            organization_id: Overrides the caller's tenant. Needed for the
                events that *create* the tenancy — at activation the actor does
                not belong to an organisation yet, so the recorder's own context
                is empty and the new id has to be supplied.
            metadata: Which fields changed. **Never a secret value** — see
                :mod:`src.modules.organizations.models.audit`.
        """
        try:
            await self._repo.append(
                event=str(event),
                actor_user_id=self._actor_user_id,
                actor_email=self._actor_email,
                organization_id=organization_id or self._organization_id,
                target_type=target_type,
                target_id=None if target_id is None else str(target_id),
                ip_address=self._ip_address,
                user_agent=self._user_agent,
                metadata=metadata,
            )
        except Exception:
            # Deliberately broad, and deliberately swallowed: see the module
            # docstring. The alternative is that a failing log prevents a
            # security action from being taken, which is the worse failure.
            logger.exception(
                "Could not record audit event %s (actor=%s, target=%s:%s).",
                event,
                self._actor_user_id,
                target_type,
                target_id,
            )


async def read_trail(
    repo: AuditLogRepository, *, organization_id: uuid.UUID, limit: int
) -> list[AuditLogEntry]:
    """Return one organisation's audit trail, newest first.

    A module-level function rather than a method on :class:`AuditRecorder`,
    because reading and writing this table are different acts with different
    callers: the recorder is bound to one request's actor and exists to append,
    while this is a query on behalf of an owner looking at their own company.

    There is deliberately **no un-scoped variant**. The one mistake worth
    designing out of an audit trail is showing one customer another customer's,
    and the way to design it out is to leave no function that could.

    Args:
        repo: The audit repository on the request's session.
        organization_id: The tenant whose trail is being read.
        limit: Hard cap on rows returned; the caller validates the range.

    Returns:
        Up to ``limit`` entries, newest first.
    """
    return await repo.list_for_organization(organization_id, limit=limit)


__all__ = ["AuditRecorder", "read_trail"]
