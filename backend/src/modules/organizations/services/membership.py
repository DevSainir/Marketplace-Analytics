"""Reading and administering the caller's own organisation.

Three jobs, all scoped to the organisation the caller already belongs to —
nothing here takes an organisation id from a request, because there is exactly
one the caller may act on and it comes from their membership:

* :meth:`OrganizationService.describe` builds the ``/me`` payload the SPA boots
  from — one response rather than three, because the router guard blocks the
  first paint until it knows the role, the tenant and the subscription state.
* :meth:`OrganizationService.list_members` is the owner's roster.
* :meth:`OrganizationService.remove_member` is how access is actually
  withdrawn. Revoking an invitation does not do it once accepted; this does.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError, ValidationError
from src.core.logging import get_logger
from src.modules.organizations.models import ALL_MODULES, AccessLevel, MemberRole, ModuleKey
from src.modules.organizations.repos import (
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.schemas import (
    MemberRead,
    MeResponse,
    OrganizationRead,
    SubscriptionRead,
)
from src.modules.organizations.services.access import (
    OrganizationAccess,
    subscription_state,
)
from src.modules.users.contract import load_emails

logger = get_logger(__name__)


class OrganizationService:
    """Reads and administration of one organisation, always the caller's own."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        organization_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        """Store the session (for the cross-module email lookup) and the repos."""
        self._session = session
        self._organizations = organization_repo
        self._memberships = membership_repo
        self._subscriptions = subscription_repo

    async def describe(self, *, access: OrganizationAccess, email: str) -> MeResponse:
        """Build the single payload the SPA decides its whole shape from.

        Args:
            access: The caller's resolved access, from the request dependency.
            email: Their login email, for the header.

        Returns:
            Role, feature flags, and — when they belong to one — their
            organisation and its subscription. All three are ``None`` for a
            freshly registered account, which is what tells the SPA to render
            the «введите ключ активации» screen instead of the app.
        """
        payload = MeResponse(
            user_id=access.user_id,
            email=email,
            role=access.role,
            internal_features=access.sees_internal_features,
            can_write=access.can_write,
        )
        if access.organization_id is None:
            return payload

        organization = await self._organizations.get_by_id(access.organization_id)
        if organization is not None:
            payload.organization = OrganizationRead.model_validate(organization)
        subscription = await self._subscriptions.get_for_organization(access.organization_id)
        if subscription is not None:
            payload.subscription = SubscriptionRead(
                started_at=subscription.started_at,
                expires_at=subscription.expires_at,
                state=subscription_state(subscription),
                max_workspaces=subscription.max_workspaces,
                max_managers=subscription.max_managers,
            )
        return payload

    async def list_members(self, *, organization_id: uuid.UUID) -> list[MemberRead]:
        """List the organisation's members, owner first.

        Emails come from the users module through its contract, in one bulk
        lookup — a query per member would make this page cost scale with the
        team.
        """
        memberships = await self._memberships.list_for_organization(organization_id)
        emails = await load_emails(self._session, {m.user_id for m in memberships})
        return [
            MemberRead(
                user_id=m.user_id,
                # A membership whose account was deleted is skipped by the FK's
                # cascade, so a missing email here means a race, not a gap worth
                # failing the page over.
                email=emails.get(m.user_id, "—"),
                role=m.role,
                joined_at=m.joined_at,
                access_level=AccessLevel(m.access_level),
                modules=[ModuleKey(k) for k in m.modules if k in ALL_MODULES],
            )
            for m in memberships
            if m.user_id in emails
        ]

    async def set_member_access(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        access_level: AccessLevel,
        modules: Sequence[ModuleKey],
    ) -> MemberRead:
        """Set one manager's level and module grant.

        Scoped to the caller's organisation on the way in, so an owner cannot
        reach a membership in another company by guessing a user id — the
        lookup is by the pair, never by ``user_id`` alone.

        The owner is refused rather than silently ignored: an owner writes
        everywhere by definition, and a UI that appeared to set them read-only
        would be showing a state the guards do not honour.

        Args:
            organization_id: The caller's organisation.
            user_id: The member being changed.
            access_level: The new level.
            modules: The surfaces they may reach.

        Returns:
            The member as it now stands.

        Raises:
            NotFoundError: No such member in this organisation.
            ValidationError: The target is the owner.
        """
        membership = await self._memberships.get_for_organization_member(
            organization_id=organization_id, user_id=user_id
        )
        if membership is None:
            raise NotFoundError("Участник не найден в этой организации.")
        if membership.role == MemberRole.OWNER.value:
            raise ValidationError("Доступ владельца изменить нельзя.")

        membership.access_level = access_level.value
        membership.modules = [m.value for m in modules]
        await self._session.flush()

        emails = await load_emails(self._session, {membership.user_id})
        return MemberRead(
            user_id=membership.user_id,
            email=emails.get(membership.user_id, "—"),
            role=membership.role,
            joined_at=membership.joined_at,
            access_level=access_level,
            modules=list(modules),
        )

    async def rename(self, *, organization_id: uuid.UUID, name: str) -> OrganizationRead:
        """Set the organisation's display name.

        Raises:
            NotFoundError: The organisation no longer exists.
        """
        organization = await self._organizations.get_by_id(organization_id)
        if organization is None:
            raise NotFoundError("Организация не найдена.")
        await self._organizations.rename(organization, name=name)
        return OrganizationRead.model_validate(organization)

    async def remove_member(self, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Remove a manager, returning that account to the ``user`` role.

        Their data stays — it belongs to the organisation, not to them — and
        they simply stop being able to reach it.

        Raises:
            NotFoundError: No such member in this organisation. A membership in
                a different organisation reads the same, so this is not an
                oracle for other companies' rosters.
            ValidationError: The target is the owner. An organisation without an
                owner has nobody who can invite, rename or renew it, and there
                is no path back — so it is refused rather than made
                recoverable-in-principle.
        """
        membership = await self._memberships.get_for_user(user_id)
        if membership is None or membership.organization_id != organization_id:
            raise NotFoundError("Участник не найден.")
        if membership.role == MemberRole.OWNER.value:
            raise ValidationError("Владельца организации нельзя удалить.")
        await self._memberships.delete(membership)
        logger.info("User %s removed from organisation %s.", user_id, organization_id)


async def load_workspace_quota(session: AsyncSession, organization_id: uuid.UUID) -> int | None:
    """Return an organisation's workspace cap, or ``None`` for unlimited.

    A module-level loader (not a service method) because its consumer is the
    workspaces module, reached through ``contract.py`` — the same pattern the
    finreports routers use to read monitoring's per-SKU facts.

    Args:
        session: An open async session (caller owns the transaction).
        organization_id: The tenant whose cap is wanted.

    Returns:
        The cap, or ``None`` when unlimited — which is also what a missing
        subscription returns. That is deliberate: the quota is a commercial
        limit, and the access gate (which fails CLOSED on a missing row) is
        what actually decides whether the tenant may write at all.
    """
    subscription = await SubscriptionRepository(session).get_for_organization(organization_id)
    return subscription.max_workspaces if subscription else None
