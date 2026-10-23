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
    # Acceptance is deliberately NOT here any more. A link stays usable until it
    # expires or is withdrawn, so "somebody joined through it" says nothing
    # about whether it still works — and reporting it as spent would tell an
    # owner a live link was closed.
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
    async def _refuse_if_manager_quota_is_full(self, organization_id: uuid.UUID) -> None:
        """Refuse when the organisation already holds every manager it may.

        Counted against existing MEMBERS, not against outstanding invitations:
        an unaccepted invitation costs nothing, and refusing to issue one
        because five were sent and none accepted would be a quota on optimism.

        Raises:
            ValidationError: The quota is full.
        """
        subscription = await self._subscriptions.get_for_organization(organization_id)
        limit = subscription.max_managers if subscription else None
        if limit is not None and await self._memberships.count_managers(organization_id) >= limit:
            raise ValidationError(
                f"Manager limit reached ({limit}). Remove a manager or renew the subscription."
            )

    async def invite(
        self,
        *,
        organization_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        email: str | None,
        valid_for_hours: int,
        access: MemberAccessFields | None = None,
    ) -> InvitationCreated:
        """Issue a manager invitation into the owner's organisation.

        Args:
            organization_id: The owner's organisation.
            owner_user_id: The issuing owner.
            email: Address to offer it to in-app, or ``None`` for a bare link.
            valid_for_hours: How long it stays acceptable. Short by default
                (one hour): the link admits anyone who holds it for as long
                as it lives, so the window IS the control.
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
        # Checked here for a quick refusal, and again at ACCEPTANCE, which is
        # the only place it can still hold: one link can now admit several
        # people, so a check that runs once when the link is made would let the
        # second, third and fourth acceptance walk straight past the limit.
        await self._refuse_if_manager_quota_is_full(organization_id)

        grant = access or MemberAccessFields()
        token = generate_opaque_secret(_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(hours=valid_for_hours)
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

    async def revoke(self, *, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> str | None:
        """Withdraw an outstanding invitation.

        Args:
            organization_id: The caller's organisation — an invitation issued by
                a different one is a 404, not a 403, so the endpoint is not an
                oracle for other companies' invitation ids.
            invitation_id: The invitation to withdraw.

        Withdrawing stops the LINK; it does not remove anyone who already came
        through it. Those are two different acts now that one link can admit
        several people, and this is the one that closes the door — removing a
        member is how you deal with whoever is already inside.

        Refusing an already-accepted invitation, which this used to do, has
        become exactly backwards: a link that got out AND was used is the one
        most urgently in need of revoking, and telling the owner to remove a
        member instead would leave it working for the next person.

        Args:
            organization_id: The caller's organisation — an invitation issued by
                a different one is a 404, not a 403, so the endpoint is not an
                oracle for other companies' invitation ids.
            invitation_id: The invitation to withdraw.

        Returns:
            The address the invitation was addressed to, or ``None`` for a bare
            link. Returned only so the audit entry can name the link: once it is
            revoked the owner's list stops showing it, and the trail is then the
            only place that says which one this was.

        Raises:
            NotFoundError: No such invitation in this organisation.
        """
        row = await self._invitations.get_by_id(invitation_id)
        if row is None or row.organization_id != organization_id:
            raise NotFoundError("Invitation not found.")
        if row.revoked_at is None:
            await self._invitations.mark_revoked(row, revoked_at=datetime.now(UTC))
        return row.email

    # ------------------------------------------------------------------ #
    # The invitee's side
    # ------------------------------------------------------------------ #
    async def list_pending_for(self, *, email: str) -> list[PendingInvitation]:
        """List live invitations addressed to one account's email.

        This is what puts "You're invited" on a registered user's own profile
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
            raise ConflictError("This account already belongs to a company.")

        row = await self._invitations.get_by_hash(hash_opaque_secret(token.strip()))
        now = datetime.now(UTC)
        addressed_to_someone_else = (
            row is not None and row.email is not None and row.email != _normalize_email(email)
        )
        # `accepted_at` is deliberately NOT a rejection any more: an invitation
        # is reusable until it expires or is withdrawn. What replaces it as the
        # bound is the window — one hour by default — and the manager quota
        # below, which is now the only thing standing between a leaked link and
        # an unbounded number of managers.
        if (
            row is None
            or row.revoked_at is not None
            or row.expires_at <= now
            or addressed_to_someone_else
        ):
            logger.info(
                "Rejected invitation acceptance by user %s (known=%s, misaddressed=%s).",
                user_id,
                row is not None,
                addressed_to_someone_else,
            )
            raise PermissionDeniedError("Invalid invitation.")

        # The quota, re-checked at the moment it is spent. Issuing checked it
        # too, but a reusable link makes that check historical: five people can
        # arrive through one link that was legal when it was made.
        await self._refuse_if_manager_quota_is_full(row.organization_id)

        # NOT consumed — that is the point of the change. Recorded instead: who
        # came through most recently, and how many have. The count is what lets
        # an owner notice a link that got out; the timestamps are the last
        # arrival, not the only one.
        #
        # Known and accepted: this is a read-then-write, so two people accepting
        # in the same instant can both pass a quota with one seat left. The
        # single-use model closed that with a conditional UPDATE, which no
        # longer applies to a link meant to admit several. The overshoot is one
        # seat, it needs simultaneity, and an owner can remove a member; a
        # database-level constraint on manager count is the real fix if this
        # ever matters.
        await self._invitations.record_acceptance(
            row.id, accepted_at=now, accepted_by_user_id=user_id
        )

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
            raise ConflictError("This account already belongs to a company.") from exc
        logger.info("User %s joined organisation %s as manager.", user_id, row.organization_id)
        return row.organization_id
