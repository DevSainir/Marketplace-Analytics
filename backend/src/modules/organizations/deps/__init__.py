"""Dependency-injection wiring and the access guards for the whole platform.

Besides the usual repository → service graph, this package owns the four guards
every protected route in every module is built from. They are declared here
rather than in ``core/deps.py`` because they are domain decisions — what a role
means, what a lapsed subscription costs — and ``core`` holds infrastructure
only.

The access guards themselves live in :mod:`.guards` and are re-exported here,
so every caller keeps importing them from the package.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from src.core.client_ip import resolve_client_ip
from src.core.deps import DbSession
from src.modules.organizations.deps.guards import (
    AbTestsAccess,
    CodeIssuerAccess,
    CurrentAccess,
    DevAccess,
    FinreportsAccess,
    InternalAccess,
    MemberAccess,
    MonitoringAccess,
    OwnerAccess,
    WritingAccess,
    get_current_access,
    require_ab_tests,
    require_advertising,
    require_any_module,
    require_code_issuer,
    require_dev,
    require_finreports,
    require_groups,
    require_heatmap,
    require_internal,
    require_member,
    require_module,
    require_monitoring,
    require_owner,
    require_summary,
    require_writer,
)
from src.modules.organizations.repos import (
    ActivationCodeRepository,
    AuditLogRepository,
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.services.activation import ActivationService
from src.modules.organizations.services.audit import AuditRecorder
from src.modules.organizations.services.invitations import InvitationService
from src.modules.organizations.services.membership import OrganizationService
from src.modules.users.contract import CurrentUser


# --------------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------------- #
def get_organization_repo(session: DbSession) -> OrganizationRepository:
    """Provide an :class:`OrganizationRepository` bound to the request session."""
    return OrganizationRepository(session)


def get_membership_repo(session: DbSession) -> MembershipRepository:
    """Provide a :class:`MembershipRepository` bound to the request session."""
    return MembershipRepository(session)


def get_subscription_repo(session: DbSession) -> SubscriptionRepository:
    """Provide a :class:`SubscriptionRepository` bound to the request session."""
    return SubscriptionRepository(session)


def get_activation_code_repo(session: DbSession) -> ActivationCodeRepository:
    """Provide an :class:`ActivationCodeRepository` bound to the request session."""
    return ActivationCodeRepository(session)


def get_invitation_repo(session: DbSession) -> InvitationRepository:
    """Provide an :class:`InvitationRepository` bound to the request session."""
    return InvitationRepository(session)


OrganizationRepoDep = Annotated[OrganizationRepository, Depends(get_organization_repo)]
MembershipRepoDep = Annotated[MembershipRepository, Depends(get_membership_repo)]
SubscriptionRepoDep = Annotated[SubscriptionRepository, Depends(get_subscription_repo)]
ActivationCodeRepoDep = Annotated[ActivationCodeRepository, Depends(get_activation_code_repo)]
InvitationRepoDep = Annotated[InvitationRepository, Depends(get_invitation_repo)]


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #
def get_organization_service(
    session: DbSession,
    organization_repo: OrganizationRepoDep,
    membership_repo: MembershipRepoDep,
    subscription_repo: SubscriptionRepoDep,
) -> OrganizationService:
    """Compose the read/administration service for the caller's organisation."""
    return OrganizationService(
        session=session,
        organization_repo=organization_repo,
        membership_repo=membership_repo,
        subscription_repo=subscription_repo,
    )


def get_activation_service(
    code_repo: ActivationCodeRepoDep,
    organization_repo: OrganizationRepoDep,
    membership_repo: MembershipRepoDep,
    subscription_repo: SubscriptionRepoDep,
) -> ActivationService:
    """Compose the activation-code issue/redeem service."""
    return ActivationService(
        code_repo=code_repo,
        organization_repo=organization_repo,
        membership_repo=membership_repo,
        subscription_repo=subscription_repo,
    )


def get_invitation_service(
    invitation_repo: InvitationRepoDep,
    membership_repo: MembershipRepoDep,
    organization_repo: OrganizationRepoDep,
    subscription_repo: SubscriptionRepoDep,
) -> InvitationService:
    """Compose the invitation issue/accept service."""
    return InvitationService(
        invitation_repo=invitation_repo,
        membership_repo=membership_repo,
        organization_repo=organization_repo,
        subscription_repo=subscription_repo,
    )


OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]
ActivationServiceDep = Annotated[ActivationService, Depends(get_activation_service)]
InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #
def get_audit_repo(session: DbSession) -> AuditLogRepository:
    """Provide the audit repository bound to the request session."""
    return AuditLogRepository(session)


AuditRepoDep = Annotated[AuditLogRepository, Depends(get_audit_repo)]


def get_audit_recorder(
    session: DbSession,
    request: Request,
    user: CurrentUser,
    access: CurrentAccess,
) -> AuditRecorder:
    """Provide a recorder with this request's actor already resolved.

    Declared on ``CurrentAccess`` rather than ``MemberAccess``, because two of
    the events worth recording — redeeming an activation code and accepting an
    invitation — happen precisely when the caller has no organisation yet, and a
    stricter guard would exclude the moment a tenancy is created.

    The address comes from :func:`~src.core.client_ip.resolve_client_ip`, so the
    trail records what nginx observed and never a value the client chose. An
    audit log that believes ``X-Forwarded-For`` records the attacker's opinion of
    where they were.
    """
    return AuditRecorder(
        repo=AuditLogRepository(session),
        actor_user_id=user.id,
        actor_email=user.email,
        organization_id=access.organization_id,
        ip_address=resolve_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


AuditTrail = Annotated[AuditRecorder, Depends(get_audit_recorder)]


def get_unauthenticated_audit_recorder(session: DbSession, request: Request) -> AuditRecorder:
    """Provide a recorder for a route with no access token.

    Password reset is the case: the caller proves who they are with a code sent
    to their mailbox, so :func:`get_audit_recorder` cannot be used — it depends
    on ``CurrentUser`` and would turn an unauthenticated route into an
    authenticated one.

    The actor is therefore empty here and the route passes the identity it
    established to :meth:`AuditRecorder.record`. What this dependency still
    supplies is the half a route cannot fake: the address nginx observed and the
    user agent. "Somebody holding that mailbox changed the password, from this
    IP" is the sentence an incident needs, and none of it is worth having if the
    route could not record it at all.
    """
    return AuditRecorder(
        repo=AuditLogRepository(session),
        ip_address=resolve_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


UnauthenticatedAuditTrail = Annotated[AuditRecorder, Depends(get_unauthenticated_audit_recorder)]

__all__ = [
    "AbTestsAccess",
    "ActivationServiceDep",
    "AuditRepoDep",
    "AuditTrail",
    "CodeIssuerAccess",
    "CurrentAccess",
    "DevAccess",
    "FinreportsAccess",
    "InternalAccess",
    "InvitationServiceDep",
    "MemberAccess",
    "MonitoringAccess",
    "OrganizationServiceDep",
    "OwnerAccess",
    "UnauthenticatedAuditTrail",
    "WritingAccess",
    "get_audit_recorder",
    "get_audit_repo",
    "get_current_access",
    "get_unauthenticated_audit_recorder",
    "require_ab_tests",
    "require_advertising",
    "require_any_module",
    "require_code_issuer",
    "require_dev",
    "require_finreports",
    "require_groups",
    "require_heatmap",
    "require_internal",
    "require_member",
    "require_module",
    "require_monitoring",
    "require_owner",
    "require_summary",
    "require_writer",
]
