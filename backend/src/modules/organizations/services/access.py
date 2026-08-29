"""Who the caller is, what they may reach, and whether their tenant has paid.

This module answers one question — :func:`resolve_access` — and every guard in
every module is built on its answer. It is deliberately the only place that
combines the three facts that decide a request:

1. the **platform role** on ``auth.users`` (``dev`` or ``user``),
2. the caller's **membership**, if any (``owner`` or ``manager``),
3. their organisation's **subscription state**.

**Why the roles live in two places.** ``dev`` is a property of a person, not of
a membership: a dev sees every feature regardless of which organisation they
happen to belong to, or whether they belong to one at all. ``owner`` and
``manager`` are properties of a membership, because they mean nothing without
the company they are held in. Folding them into one column would make "dev who
also owns a company" unrepresentable, and that is exactly the state our own
accounts are in.

:class:`EffectiveRole` is what the rest of the codebase reads. It collapses the
two sources in one place, with one rule — **dev outranks everything** — so no
route ever has to remember to check both.

**Fail closed.** Every ambiguity here resolves toward less access: no
membership is :attr:`EffectiveRole.USER` (which reaches nothing), and a missing
subscription row is :attr:`SubscriptionState.READ_ONLY` rather than an
exception. A tenant seeing a stale paywall is a support message; a tenant
reading another company's settlement report is not recoverable.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import PermissionDeniedError
from src.modules.organizations.models import MemberRole, Subscription
from src.modules.organizations.repos import (
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)


class EffectiveRole(enum.StrEnum):
    """The caller's role as the rest of the application sees it.

    One value, resolved from the platform role and the membership together, so
    a route guard never has to consult two sources and never has to remember
    which one wins.
    """

    #: Us. Every feature, every internal surface, no subscription gate.
    DEV = "dev"
    #: Bought the subscription. Controls workspaces and managers.
    OWNER = "owner"
    #: Invited into an organisation. Full access to its workspaces.
    MANAGER = "manager"
    #: Registered, belongs to nothing, may reach nothing.
    USER = "user"


class SubscriptionState(enum.StrEnum):
    """Where an organisation sits on the expiry ramp.

    See :mod:`src.modules.organizations.models.subscription` for why expiry is
    a ramp rather than a cliff.
    """

    #: Paid up. Everything works.
    ACTIVE = "active"
    #: Lapsed, inside the grace window. Everything still works; the UI warns.
    GRACE = "grace"
    #: Past grace. Reads answer; writes and WB refreshes are refused.
    READ_ONLY = "read_only"


def subscription_state(
    subscription: Subscription | None, *, now: datetime | None = None
) -> SubscriptionState:
    """Place a subscription on the expiry ramp.

    Pure, and takes its clock as an argument, so the boundaries are testable
    without freezing time globally.

    Args:
        subscription: The organisation's term, or ``None`` when it has none.
        now: The instant to judge against; defaults to the current UTC time.

    Returns:
        The state. ``None`` in means :attr:`SubscriptionState.READ_ONLY` —
        a tenant with no term has not paid, and the safe reading of a row that
        should exist and does not is "no access to write", never "full access".
    """
    if subscription is None:
        return SubscriptionState.READ_ONLY
    moment = now or datetime.now(UTC)
    if moment < subscription.expires_at:
        return SubscriptionState.ACTIVE
    if moment < subscription.expires_at + timedelta(days=subscription.grace_days):
        return SubscriptionState.GRACE
    return SubscriptionState.READ_ONLY


@dataclass(frozen=True, slots=True)
class OrganizationAccess:
    """Everything a request needs to know about who is asking.

    Resolved once per request by the dependency in ``deps/`` and passed down.
    Frozen because a guard that could mutate it would be a guard that could
    escalate it.

    Attributes:
        user_id: The authenticated account.
        organization_id: Their organisation, or ``None`` when they have no
            membership (the ``user`` role, and a dev who belongs to nobody).
        role: The collapsed :class:`EffectiveRole`.
        subscription: Where their organisation sits on the expiry ramp.
        is_primary_org: ``True`` when their organisation is OURS — which is
            what unlocks the internal-only surfaces for its members.
    """

    user_id: uuid.UUID
    organization_id: uuid.UUID | None
    role: EffectiveRole
    subscription: SubscriptionState
    is_primary_org: bool

    @property
    def tenant_id(self) -> uuid.UUID:
        """The caller's organisation, as a value that cannot be ``None``.

        Every route behind ``MemberAccess`` / ``WritingAccess`` / ``OwnerAccess``
        already has one, but ``organization_id`` is typed optional because
        callers in front of those guards legitimately do not. Reading it through
        here is what lets those routes pass it to a service without an
        ``assert`` — which would be stripped under ``python -O`` and is the
        wrong tool for something that decides tenancy.

        Raises:
            PermissionDeniedError: The caller has no organisation. Unreachable
                behind the guards; if a route is ever wired without one, this
                fails the request closed instead of scoping a query to ``None``.
        """
        if self.organization_id is None:
            raise PermissionDeniedError("Аккаунт не привязан к организации.")
        return self.organization_id

    @property
    def is_dev(self) -> bool:
        """Whether the caller is us."""
        return self.role is EffectiveRole.DEV

    @property
    def can_write(self) -> bool:
        """Whether this request may change anything.

        Two independent conditions, both required: the caller must hold a role
        that writes at all, and their tenant must not have fallen past its
        grace window. A dev is exempt from the second — our own access must not
        depend on our own billing rows, or a bad backfill locks out the people
        who would fix it.
        """
        if self.role is EffectiveRole.DEV:
            return True
        if self.role is EffectiveRole.USER:
            return False
        return self.subscription is not SubscriptionState.READ_ONLY

    @property
    def sees_internal_features(self) -> bool:
        """Whether the internal-only surfaces are reachable for this caller.

        one seller — ours — against our own data and our own legal case. They
        are reachable by devs and by members of the primary organisation, and
        by nobody else.
        """
        return self.is_dev or self.is_primary_org


async def resolve_access(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    platform_role: str,
    now: datetime | None = None,
) -> OrganizationAccess:
    """Resolve one caller's complete access picture.

    Three reads on the request's own session: the membership, the organisation,
    and the subscription. They are three rather than one join because the first
    usually answers the question on its own — a caller with no membership needs
    neither of the others, and that is the whole ``user`` role.

    Args:
        session: The request-scoped session.
        user_id: The authenticated account, from the access token.
        platform_role: ``auth.users.role`` for that account.
        now: Clock override for the subscription ramp (tests).

    Returns:
        The caller's :class:`OrganizationAccess`.
    """
    is_dev = platform_role == EffectiveRole.DEV.value
    membership = await MembershipRepository(session).get_for_user(user_id)

    if membership is None:
        # A dev with no membership still sees everything; anyone else sees
        # nothing. Subscription is irrelevant either way — there is no tenant to
        # bill — so it reports READ_ONLY, which is what "may not write tenant
        # data" means for a caller with no tenant.
        return OrganizationAccess(
            user_id=user_id,
            organization_id=None,
            role=EffectiveRole.DEV if is_dev else EffectiveRole.USER,
            subscription=SubscriptionState.READ_ONLY,
            is_primary_org=False,
        )

    organization = await OrganizationRepository(session).get_by_id(membership.organization_id)
    subscription = await SubscriptionRepository(session).get_for_organization(
        membership.organization_id
    )
    # dev outranks the membership role, but the membership still supplies the
    # organisation: a dev who owns a company works inside it like anyone else,
    # and only their ROLE is elevated.
    role = EffectiveRole.DEV if is_dev else EffectiveRole(membership.role)
    return OrganizationAccess(
        user_id=user_id,
        organization_id=membership.organization_id,
        role=role,
        subscription=subscription_state(subscription, now=now),
        is_primary_org=bool(organization and organization.is_primary),
    )


#: Roles permitted to act inside an organisation's workspaces at all.
WRITING_ROLES: frozenset[EffectiveRole] = frozenset(
    {EffectiveRole.DEV, EffectiveRole.OWNER, EffectiveRole.MANAGER}
)

__all__ = [
    "WRITING_ROLES",
    "EffectiveRole",
    "MemberRole",
    "OrganizationAccess",
    "SubscriptionState",
    "resolve_access",
    "subscription_state",
]
