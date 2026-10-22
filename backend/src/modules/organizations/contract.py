"""Public contract for the Organizations module.

The stable, import-safe surface other modules may consume. Per the "no
horizontal imports" rule, external modules import organisation capabilities
from here only — never from ``services``/``repos``/``models`` internals.

What crosses this boundary is deliberately one idea: **who is asking, and what
may they do.** Two layers of it:

* the *answer* — :func:`resolve_access` computes it, :class:`OrganizationAccess`
  carries it, and :class:`EffectiveRole` / :class:`SubscriptionState` are the
  enums needed to read it;
* the *guards* — the ``Annotated`` dependencies every other module's routers
  declare. They are exported here rather than reimplemented per module, which
  is the point: "what a manager may do" is decided once, and a router that
  wants a different answer has to change this module rather than quietly
  disagree with it in its own ``deps``.

A third thing crosses too, and it is deliberately narrow: **the audit trail.**
``AuditTrail`` is a request-scoped recorder with the actor already resolved,
``UnauthenticatedAuditTrail`` is the same recorder for a route that has no access
token to resolve one from, and ``AuditEvent`` is the closed set of things worth
recording. Other modules get to
say *that* a workspace was deleted or a token rotated without learning anything
about the table underneath — which is why the enum is exported and the ORM model
is not.

Nothing here exposes an ORM model, so the tables underneath stay free to move.
"""

from src.modules.organizations.deps import (
    AbTestsAccess,
    AuditTrail,
    CurrentAccess,
    DevAccess,
    FinreportsAccess,
    MemberAccess,
    MonitoringAccess,
    OwnerAccess,
    UnauthenticatedAuditTrail,
    WritingAccess,
    require_ab_tests,
    require_advertising,
    require_finreports,
    require_groups,
    require_heatmap,
    require_member,
    require_monitoring,
    require_owner,
    require_summary,
    require_writer,
)
from src.modules.organizations.models import ALL_MODULES, GROUP_MODULES, AuditEvent, ModuleKey
from src.modules.organizations.services import (
    WRITING_ROLES,
    AccessLevel,
    EffectiveRole,
    OrganizationAccess,
    SubscriptionState,
    harvestable_organization_ids,
    load_harvestable_organization_ids,
    load_workspace_quota,
    resolve_access,
    subscription_state,
)

__all__ = [
    "ALL_MODULES",
    "GROUP_MODULES",
    "WRITING_ROLES",
    "AbTestsAccess",
    "AccessLevel",
    "AuditEvent",
    "AuditTrail",
    "CurrentAccess",
    "DevAccess",
    "EffectiveRole",
    "FinreportsAccess",
    "MemberAccess",
    "ModuleKey",
    "MonitoringAccess",
    "OrganizationAccess",
    "OwnerAccess",
    "SubscriptionState",
    "UnauthenticatedAuditTrail",
    "WritingAccess",
    "harvestable_organization_ids",
    "load_harvestable_organization_ids",
    "load_workspace_quota",
    "require_ab_tests",
    "require_advertising",
    "require_finreports",
    "require_groups",
    "require_heatmap",
    "require_member",
    "require_monitoring",
    "require_owner",
    "require_summary",
    "require_writer",
    "resolve_access",
    "subscription_state",
]
