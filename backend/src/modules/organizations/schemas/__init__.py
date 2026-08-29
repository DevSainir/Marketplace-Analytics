"""Pydantic DTOs for the Organizations module presentation boundary.

Two rules run through every shape here, both about secrets:

* **A code or token travels outbound exactly once**, in the response that
  creates it (:class:`ActivationCodeCreated`, :class:`InvitationCreated`). It is
  stored as a SHA-256 digest, so that response is the only chance anyone has to
  copy it — which is stated in each field's description, because a UI that
  hides it behind a "show later" affordance would be promising something the
  database cannot deliver.
* **An invitation shown to its recipient names the organisation and nothing
  else** (:class:`PendingInvitation`). Who else is in it, when it expires
  internally, who issued it — none of that belongs to someone who has not
  accepted yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from src.modules.organizations.services.access import EffectiveRole, SubscriptionState


class SubscriptionRead(BaseModel):
    """An organisation's access term, as its own members see it."""

    model_config = ConfigDict(from_attributes=True)

    started_at: datetime
    expires_at: datetime
    #: Where the term sits on the active → grace → read-only ramp.
    state: SubscriptionState
    #: ``None`` = unlimited.
    max_workspaces: int | None = None
    max_managers: int | None = None


class OrganizationRead(BaseModel):
    """The caller's own organisation."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None
    is_primary: bool
    created_at: datetime


class MemberRead(BaseModel):
    """One member of the caller's organisation, for the owner's member list."""

    user_id: uuid.UUID
    email: EmailStr
    role: str
    joined_at: datetime


class MeResponse(BaseModel):
    """Everything the SPA needs to decide what to render, in one call.

    Deliberately one response rather than three: the router guard blocks the
    first paint until it knows the role, the organisation and the subscription
    state, and three round trips on that path is three chances to show a
    half-configured shell.

    ``organization``, ``subscription`` and ``members`` are all ``None`` for a
    freshly registered account — which is exactly what tells the SPA to render
    the «введите ключ активации» screen instead of the app.
    """

    user_id: uuid.UUID
    email: EmailStr
    #: The collapsed role the whole UI keys off (dev / owner / manager / user).
    role: EffectiveRole
    #: ``True`` when the internal-only surfaces should be shown.
    internal_features: bool
    #: ``False`` once the subscription is past its grace window.
    can_write: bool
    organization: OrganizationRead | None = None
    subscription: SubscriptionRead | None = None


class OrganizationRenameRequest(BaseModel):
    """Payload to rename the caller's own organisation (owner only)."""

    name: str = Field(min_length=1, max_length=256)


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
class ActivationCodeCreateRequest(BaseModel):
    """Payload for a dev generating an activation code."""

    note: str = Field(
        default="",
        max_length=256,
        description="Who this was sold to, and for how much — the only record we keep.",
    )
    valid_for_days: int | None = Field(
        default=30,
        ge=1,
        le=365,
        description="How long the code stays redeemable; null = never expires.",
    )
    subscription_days: int = Field(
        default=30,
        ge=1,
        le=3650,
        description="Term the code buys when redeemed.",
    )


class ActivationCodeCreated(BaseModel):
    """A freshly generated code — the ONE response that carries its value."""

    id: uuid.UUID
    code: str = Field(
        description="The code to hand over. Stored hashed, so it can never be shown again."
    )
    note: str
    expires_at: datetime | None
    subscription_days: int


class ActivationCodeRead(BaseModel):
    """A generated code as the dev list shows it — never its value."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    note: str
    expires_at: datetime | None
    used_at: datetime | None
    organization_id: uuid.UUID | None
    created_at: datetime


class ActivationRequest(BaseModel):
    """Payload for redeeming an activation code on ``/profile``."""

    code: str = Field(min_length=1, max_length=128, description="The code we handed over.")


# --------------------------------------------------------------------------- #
# Invitations
# --------------------------------------------------------------------------- #
class InvitationCreateRequest(BaseModel):
    """Payload for an owner inviting a manager.

    ``email`` set addresses the invitation to an existing account, which then
    finds it waiting on their own profile page; ``email`` omitted produces a
    bare link the owner passes on themselves. Both forms return a link, because
    an invited user who has not registered yet can only arrive through one.
    """

    email: EmailStr | None = Field(
        default=None,
        description="Address to offer it to in-app; omit for a link-only invitation.",
    )
    valid_for_days: int = Field(
        default=7,
        ge=1,
        le=90,
        description="How long the invitation stays acceptable.",
    )


class InvitationCreated(BaseModel):
    """A freshly issued invitation — the ONE response carrying its token."""

    id: uuid.UUID
    email: EmailStr | None
    token: str = Field(
        description="The invitation token. Stored hashed, so it can never be shown again."
    )
    expires_at: datetime


class InvitationRead(BaseModel):
    """An issued invitation as the owner's list shows it — never its token."""

    id: uuid.UUID
    email: EmailStr | None
    #: One of ``pending`` / ``accepted`` / ``revoked`` / ``expired``, resolved
    #: against the server's clock so every viewer reads the same state.
    status: str
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime


class PendingInvitation(BaseModel):
    """An invitation as its RECIPIENT sees it, before accepting.

    Carries the organisation's name and nothing else about it. Someone who has
    not accepted is not yet a member, and a preview that listed the members or
    the workspaces would leak a customer's roster to whoever was mistyped into
    the email field.
    """

    id: uuid.UUID
    organization_name: str | None
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    """Payload for accepting an invitation by its token (the link flow)."""

    token: str = Field(min_length=1, max_length=256)


__all__ = [
    "ActivationCodeCreateRequest",
    "ActivationCodeCreated",
    "ActivationCodeRead",
    "ActivationRequest",
    "InvitationAcceptRequest",
    "InvitationCreateRequest",
    "InvitationCreated",
    "InvitationRead",
    "MeResponse",
    "MemberRead",
    "OrganizationRead",
    "OrganizationRenameRequest",
    "PendingInvitation",
    "SubscriptionRead",
]
