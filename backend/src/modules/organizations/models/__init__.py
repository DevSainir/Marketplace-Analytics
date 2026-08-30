"""ORM models for the Organizations module (PostgreSQL ``organizations`` schema).

The tenancy root and everything that governs access to it, split by
responsibility rather than by size:

* :mod:`.organization` — the organisation itself and its memberships. The unit
  tenancy, billing and feature access are all decided at.
* :mod:`.subscription` — what it has paid for, and the active → grace →
  read-only ramp when that lapses.
* :mod:`.access` — the two doors in: a single-use activation code (which makes
  an owner) and an invitation (which makes a manager).
* :mod:`.audit` — the append-only record of what people did, which outlives the
  rows it describes.

A package rather than a flat ``models.py`` because the three answer different
questions and are edited for different reasons; callers import the same names
from here either way.
"""

from src.modules.organizations.models.access import ActivationCode, Invitation
from src.modules.organizations.models.audit import AuditEvent, AuditLogEntry
from src.modules.organizations.models.organization import (
    MemberRole,
    Membership,
    Organization,
)
from src.modules.organizations.models.subscription import (
    DEFAULT_SUBSCRIPTION_DAYS,
    Subscription,
)

__all__ = [
    "DEFAULT_SUBSCRIPTION_DAYS",
    "ActivationCode",
    "AuditEvent",
    "AuditLogEntry",
    "Invitation",
    "MemberRole",
    "Membership",
    "Organization",
    "Subscription",
]
