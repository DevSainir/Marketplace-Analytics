"""Dependency-injection wiring and the access guards for the whole platform.

Besides the usual repository → service graph, this package owns the four guards
every protected route in every module is built from. They are declared here
rather than in ``core/deps.py`` because they are domain decisions — what a role
means, what a lapsed subscription costs — and ``core`` holds infrastructure
only.

The guards compose, and each one is strictly narrower than the last:

``CurrentAccess``
    Resolve the caller. No requirement beyond a valid token; a registered
    account with no organisation gets through, which is what the activation and
    invitation routes need.
``MemberAccess``
    Require an organisation. This is the one that closes the platform to the
    ``user`` role — it is on every data router in the application.
``WritingAccess``
    Require an organisation AND a subscription that has not fallen past its
    grace window. On every route that changes something or spends WB budget.
``OwnerAccess``
    Require ``owner`` (or ``dev``). Workspaces, tokens, members, billing.

``InternalAccess`` is separate rather than a fifth rung: it is not more
authority inside a tenant, it is a different question — whether this caller is
one of *us*.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from src.core.client_ip import resolve_client_ip
from src.core.deps import DbSession
from src.core.exceptions import PermissionDeniedError
from src.core.logcontext import bind_tenant
from src.modules.organizations.repos import (
    ActivationCodeRepository,
    AuditLogRepository,
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.services import (
    AccessLevel,
    EffectiveRole,
    ModuleKey,
    OrganizationAccess,
    resolve_access,
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
# The access guards
# --------------------------------------------------------------------------- #
async def get_current_access(session: DbSession, user: CurrentUser) -> OrganizationAccess:
    """Resolve the caller's role, tenant and subscription state.

    Depends on ``CurrentUser`` rather than on the token's user id alone,
    because the platform role has to be read from the LIVE row: a revoked dev
    role must take effect on the next request, not when the access token
    happens to expire.
    """
    access = await resolve_access(session, user_id=user.id, platform_role=user.role)
    # From here the request's log lines name the tenant too (register P2.2).
    # Bound here rather than in the middleware because this is the first point
    # the tenant is KNOWN — it comes from a membership lookup, not the token.
    bind_tenant(access.organization_id)
    return access


#: The caller's resolved access. No requirement beyond a valid token.
CurrentAccess = Annotated[OrganizationAccess, Depends(get_current_access)]


async def require_member(access: CurrentAccess) -> OrganizationAccess:
    """Require that the caller belongs to an organisation.

    This is the guard that closes the platform to a bare registered account.
    Registration is open, so without it every new signup would land inside
    somebody's data; with it, a fresh account can reach exactly two things —
    activation and its own pending invitations.

    A dev with no organisation of their own is deliberately NOT let through
    here: the routes behind this guard are all tenant-scoped, and there is no
    tenant to scope them to. Devs read a customer's data by belonging to an
    organisation, not by bypassing the concept.

    Raises:
        PermissionDeniedError: The caller has no membership.
    """
    if access.organization_id is None:
        raise PermissionDeniedError(
            "Аккаунт не привязан к организации. Введите ключ активации или примите приглашение."
        )
    return access


MemberAccess = Annotated[OrganizationAccess, Depends(require_member)]


async def require_writer(access: MemberAccess) -> OrganizationAccess:
    """Require a member whose subscription has not fallen past its grace window.

    Applied to everything that changes state or spends WB rate budget. Reads
    stay open on purpose — the data is the customer's own, and locking them out
    of it is a hostage position rather than a payment incentive.

    Raises:
        PermissionDeniedError: The subscription is in ``read_only``.
    """
    if not access.can_write:
        # Two different reasons land here and the person can act on only one of
        # them. An owner whose term lapsed can renew; a manager the owner set to
        # read-only cannot, and telling them to renew sends them to support with
        # the wrong question.
        if access.access_level is AccessLevel.READ_ONLY and access.role is EffectiveRole.MANAGER:
            raise PermissionDeniedError(
                "Доступ только для чтения — изменения вносит владелец организации."
            )
        raise PermissionDeniedError(
            "Подписка истекла — доступ только для чтения. "
            "Продлите подписку, чтобы вносить изменения."
        )
    return access


WritingAccess = Annotated[OrganizationAccess, Depends(require_writer)]


def require_module(
    module: ModuleKey,
) -> Callable[[OrganizationAccess], Awaitable[OrganizationAccess]]:
    """Build the guard that admits callers granted one product surface.

    Declared once on each module's own ``APIRouter`` rather than on its
    routes, which is what makes it hold: a route added tomorrow inherits the
    grant instead of having to remember it, and there is exactly one line per
    module to read when asking what a surface is protected by.

    It gates reachability, not writing — ``require_writer`` already refuses a
    read-only manager, and stacking the two means a manager needs the module
    AND the level to change anything in it.

    Args:
        module: The surface this router serves.

    Returns:
        A FastAPI dependency.
    """

    async def _guard(access: MemberAccess) -> OrganizationAccess:
        if not access.can_reach(module):
            # Deliberately says the access is missing rather than that the
            # module is: "нет такого раздела" would be a lie the person cannot
            # act on, and they need to know who to ask.
            raise PermissionDeniedError(
                "Раздел недоступен для вашей учётной записи. Доступ выдаёт владелец организации."
            )
        return access

    return _guard


#: One per product surface. The bare callables are what a module's router puts
#: in ``dependencies=[...]``; the annotated forms are for a route that also
#: wants the resolved access object in its signature.
require_monitoring = require_module(ModuleKey.MONITORING)
require_finreports = require_module(ModuleKey.FINREPORTS)

MonitoringAccess = Annotated[OrganizationAccess, Depends(require_monitoring)]
FinreportsAccess = Annotated[OrganizationAccess, Depends(require_finreports)]


async def require_ab_tests(access: InternalAccess) -> OrganizationAccess:
    """Require a caller who is one of us AND granted the A/Б-тесты module.

    Written out rather than built from :func:`require_module` because that
    factory goes through :data:`MemberAccess`, and this surface must not: a dev
    with no organisation of their own reaches the internal features today, and
    routing this guard through the membership check would quietly take that
    away. :meth:`OrganizationAccess.can_reach` already answers ``True`` for a
    dev, so the module grant only ever narrows a manager.

    Raises:
        PermissionDeniedError: Not one of us, or a manager without the grant.
    """
    if not access.can_reach(ModuleKey.AB_TESTS):
        raise PermissionDeniedError(
            "Раздел недоступен для вашей учётной записи. Доступ выдаёт владелец организации."
        )
    return access


AbTestsAccess = Annotated[OrganizationAccess, Depends(require_ab_tests)]


async def require_owner(access: MemberAccess) -> OrganizationAccess:
    """Require the organisation's owner (or a dev).

    Guards the things that change who and what the organisation IS: its
    workspaces, its WB credentials, its members, its name.

    Raises:
        PermissionDeniedError: The caller is a manager.
    """
    if access.role not in (EffectiveRole.OWNER, EffectiveRole.DEV):
        raise PermissionDeniedError("Действие доступно только владельцу организации.")
    return access


OwnerAccess = Annotated[OrganizationAccess, Depends(require_owner)]


async def require_internal(access: CurrentAccess) -> OrganizationAccess:
    """Require a caller who is one of us.

    one seller, against our own data and our own legal case. Reachable by devs
    and by members of the primary organisation, by nobody else.

    Not built on :data:`MemberAccess`: a dev without an organisation still gets
    through, because these routes are ours rather than a tenant's.

    Raises:
        PermissionDeniedError: Anyone else. Phrased as "not available" rather
            than "you are not us", since to a customer this feature does not
            exist.
    """
    if not access.sees_internal_features:
        raise PermissionDeniedError("Раздел недоступен.")
    return access


InternalAccess = Annotated[OrganizationAccess, Depends(require_internal)]


async def require_dev(access: CurrentAccess) -> OrganizationAccess:
    """Require the platform ``dev`` role (activation-code administration).

    Raises:
        PermissionDeniedError: Anyone else.
    """
    if access.role is not EffectiveRole.DEV:
        raise PermissionDeniedError("Действие доступно только разработчику.")
    return access


DevAccess = Annotated[OrganizationAccess, Depends(require_dev)]


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
    "require_dev",
    "require_finreports",
    "require_internal",
    "require_member",
    "require_module",
    "require_monitoring",
    "require_owner",
    "require_writer",
]
