"""Business logic for the Organizations module.

:mod:`.access` is the one every other module depends on: it resolves a caller
into an :class:`~.access.OrganizationAccess` — their effective role, their
tenant, and where that tenant sits on the subscription ramp — and every guard
in the codebase is built on that answer.

The flows that CREATE those facts (redeeming an activation code, issuing and
accepting invitations) live beside it and are consumed only through this
module's own routers.
"""

from src.modules.organizations.services.access import (
    WRITING_ROLES,
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
    resolve_access,
    subscription_state,
)
from src.modules.organizations.services.audit import AuditRecorder
from src.modules.organizations.services.membership import load_workspace_quota

__all__ = [
    "WRITING_ROLES",
    "AuditRecorder",
    "EffectiveRole",
    "OrganizationAccess",
    "SubscriptionState",
    "load_workspace_quota",
    "resolve_access",
    "subscription_state",
]
