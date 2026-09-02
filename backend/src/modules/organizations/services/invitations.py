"""Issuing, listing, accepting and revoking manager invitations.

An owner is the only person who can widen access to their own company, and this
is the only way they can do it. Two shapes, one row (see
:mod:`src.modules.organizations.models.access`): addressed to an email, which
puts it on that account's own profile page, or a bare link the owner passes on.

**Acceptance is checked against four conditions, in this order:** the token is
known, it has not been revoked, it has not been accepted, and it has not
expired. All four fail with the same message, for the same reason the activation
code does — a caller holding a token that does not work learns only that.

**A targeted invitation is checked against the accepting account's own email.**
Without that, a link addressed to ``a@example.com`` would be accepted by whoever
it was forwarded to, and "I invited my accountant" would silently become
"someone in my accountant's inbox has our settlement reports". A link-only
invitation (``email is None``) has no such check by construction — that is what
it is for, and it is why it expires quickly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from src.core.logging import get_logger
from src.core.security import generate_opaque_secret, hash_opaque_secret
from src.modules.organizations.models import Invitation, MemberRole
from src.modules.organizations.repos import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
    SubscriptionRepository,
)
from src.modules.organizations.schemas import (
    InvitationCreated,
    InvitationRead,
    MemberAccessFields,
    PendingInvitation,
)

logger = get_logger(__name__)

#: Bytes of entropy in an invitation token. Full 256 bits: unlike an activation
#: code, nobody retypes this — it travels inside a URL.
_TOKEN_BYTES = 32


def _normalize_email(email: str) -> str:
    """Canonicalize an email for storage and comparison.

    Must match :func:`src.modules.users.services.auth._normalize_email`, or an
    invitation addressed to ``Anna@Example.com`` would never match the account
    stored as ``anna@example.com`` and the invited person would be told their
    own invitation is not theirs.
    """
    return email.strip().lower()


def _status(invitation: Invitation, *, now: datetime) -> str:
    """Collapse an invitation's timestamps into one word for the owner's list.

    Resolved server-side against one clock so every viewer reads the same
    state — an "expired" computed in the browser drifts with the device's
    timezone and its owner's patience.
    """
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.expires_at <= now:
        return "expired"
    return "pending"


class InvitationService:
    """The owner's side and the invitee's side of joining an organisation."""

    def __init__(
        self,
        *,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        organization_repo: OrganizationRepository,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        """Store the injected repository collaborators."""
        self._invitations = invitation_repo
        self._memberships = membership_repo
        self._organizations = organization_repo
        self._subscriptions = subscription_repo

    # ------------------------------------------------------------------ #
    # The owner's side
    # ------------------------------------------------------------------ #
    async def invite(
        self,
        *,
        organization_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        email: str | None,
        valid_for_days: int,
        access: MemberAccessFields | None = None,
    ) -> InvitationCreated:
        """Issue a manager invitation into the owner's organisation.

        Args:
            organization_id: The owner's organisation.
            owner_user_id: The issuing owner.
            email: Address to offer it to in-app, or ``None`` for a bare link.
            valid_for_days: How long it stays acceptable.
            access: What the resulting manager may do and see. Defaults to
                everything, matching what a manager got before the grant
                existed. Stored on the invitation so acceptance copies it
                across, rather than being applied afterwards — the gap between
                joining and being narrowed is a gap with real access in it.

        Returns:
            The invitation, in the only response carrying its token.

        Raises:
            ValidationError: The manager quota for this organisation is full.
        """
        subscription = await self._subscriptions.get_for_organization(organization_id)
        limit = subscription.max_managers if subscription else None
        # Counted against existing MEMBERS, not against outstanding invitations:
        # an unaccepted invitation costs nothing, and refusing to issue one
        # because five were sent and none accepted would be a quota on optimism.
        if limit is not None and await self._memberships.count_managers(organization_id) >= limit:
            raise ValidationError(
                f"Достигнут лимит менеджеров ({limit}). "
                "Удалите одного из текущих или продлите подписку."
            )

        grant = access or MemberAccessFields()
        token = generate_opaque_secret(_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(days=valid_for_days)
        row = await self._invitations.create(
            organization_id=organization_id,
            email=_normalize_email(email) if email else None,
            token_hash=hash_opaque_secret(token),
            role=MemberRole.MANAGER,
            created_by_user_id=owner_user_id,
            expires_at=expires_at,
            access_level=grant.access_level.value,
            modules=[m.value for m in grant.modules],
        )
        logger.info(
            "Invitation %s issued into organisation %s by %s (targeted=%s).",
            row.id,
            organization_id,
            owner_user_id,
            email is not None,
        )
        return InvitationCreated(id=row.id, email=row.email, token=token, expires_at=expires_at)

    async def list_issued(self, *, organization_id: uuid.UUID) -> list[InvitationRead]:
        """List every invitation the organisation has issued, newest first."""
        now = datetime.now(UTC)
        rows = await self._invitations.list_for_organization(organization_id)
        return [
            InvitationRead(
                id=row.id,
                email=row.email,
                status=_status(row, now=now),
                expires_at=row.expires_at,
                accepted_at=row.accepted_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def revoke(self, *, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        """Withdraw an outstanding invitation.

        Args:
            organization_id: The caller's organisation — an invitation issued by
                a different one is a 404, not a 403, so the endpoint is not an
                oracle for other companies' invitation ids.
            invitation_id: The invitation to withdraw.

        Raises:
            NotFoundError: No such invitation in this organisation.
            ConflictError: It has already been accepted; a membership exists and
                revoking the invitation would not remove it. Remove the member
                instead, so the destructive action is the one that was asked for.
        """
        row = await self._invitations.get_by_id(invitation_id)
        if row is None or row.organization_id != organization_id:
            raise NotFoundError("Приглашение не найдено.")
        if row.accepted_at is not None:
            raise ConflictError("Приглашение уже принято. Чтобы закрыть доступ, удалите участника.")
        if row.revoked_at is None:
            await self._invitations.mark_revoked(row, revoked_at=datetime.now(UTC))

    # ------------------------------------------------------------------ #
    # The invitee's side
    # ------------------------------------------------------------------ #
    async def list_pending_for(self, *, email: str) -> list[PendingInvitation]:
        """List live invitations addressed to one account's email.

        This is what puts «Вас пригласили» on a registered user's own profile
        page — no link needed, so an owner inviting a colleague who already has
        an account does not have to get a URL to them.
        """
        now = datetime.now(UTC)
        rows = await self._invitations.list_pending_for_email(_normalize_email(email))
        live = [row for row in rows if row.expires_at > now]
        out: list[PendingInvitation] = []
        for row in live:
            organization = await self._organizations.get_by_id(row.organization_id)
            out.append(
                PendingInvitation(
                    id=row.id,
                    organization_name=organization.name if organization else None,
                    expires_at=row.expires_at,
                )
            )
        return out

    async def accept(self, *, token: str, user_id: uuid.UUID, email: str) -> uuid.UUID:
        """Accept an invitation, joining its organisation as a manager.

        Args:
            token: The invitation token (from the link, or from the in-app card).
            user_id: The accepting account.
            email: That account's email, checked against a targeted invitation.

        Returns:
            The organisation joined.

        Raises:
            PermissionDeniedError: Unknown, revoked, already accepted, expired,
                or addressed to somebody else — one message for all of them.
            ConflictError: The caller already belongs to an organisation.
        """
        existing = await self._memberships.get_for_user(user_id)
        if existing is not None:
            raise ConflictError("Этот аккаунт уже состоит в организации.")

        row = await self._invitations.get_by_hash(hash_opaque_secret(token.strip()))
        now = datetime.now(UTC)
        addressed_to_someone_else = (
            row is not None and row.email is not None and row.email != _normalize_email(email)
        )
        if (
            row is None
            or row.revoked_at is not None
            or row.accepted_at is not None
            or row.expires_at <= now
            or addressed_to_someone_else
        ):
            logger.info(
                "Rejected invitation acceptance by user %s (known=%s, misaddressed=%s).",
                user_id,
                row is not None,
                addressed_to_someone_else,
            )
            raise PermissionDeniedError("Приглашение недействительно.")

        # Consume BEFORE joining, for the reason the activation code does: the
        # checks above are a read-then-write, and a link forwarded to two people
        # who open it in the same second would otherwise admit both. The
        # conditional UPDATE also re-tests `revoked_at`, so an owner revoking
        # while someone accepts resolves one way rather than both.
        if not await self._invitations.claim(row.id, accepted_at=now, accepted_by_user_id=user_id):
            logger.info("User %s lost the race to accept invitation %s.", user_id, row.id)
            raise PermissionDeniedError("Приглашение недействительно.")

        try:
            await self._memberships.create(
                organization_id=row.organization_id,
                user_id=user_id,
                role=MemberRole(row.role),
                invited_by_user_id=row.created_by_user_id,
                access_level=row.access_level,
                modules=list(row.modules or []),
            )
        except IntegrityError as exc:
            # The request transaction rolls back, which un-claims the
            # invitation too — so a caller who already belongs somewhere does
            # not burn somebody else's invitation on the way to being refused.
            raise ConflictError("Этот аккаунт уже состоит в организации.") from exc
        logger.info("User %s joined organisation %s as manager.", user_id, row.organization_id)
        return row.organization_id
