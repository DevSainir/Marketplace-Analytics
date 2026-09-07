"""Pydantic DTOs for the Workspaces module presentation boundary.

Token *values* only ever travel inbound (set/rotate). Outbound responses carry
booleans describing which surfaces are configured — a stored WB token is never
echoed back, encrypted or otherwise.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRead(BaseModel):
    """Public representation of a workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    is_primary: bool
    created_at: datetime


class WorkspaceListResponse(BaseModel):
    """Every workspace visible to the caller (all of them, for now)."""

    items: list[WorkspaceRead]


class WorkspaceCreateRequest(BaseModel):
    """Payload to create a new workspace."""

    name: str = Field(min_length=1, max_length=256, description="Unique workspace name.")


class WorkspaceTokensUpdateRequest(BaseModel):
    """Payload to set/rotate a workspace's WB tokens.

    ``tokens`` maps a token kind (a :class:`~.models.TokenKind` slug — one of
    the 13 WB categories for a primary workspace, or ``"unified"`` for any
    other) to its value. Per entry: a non-empty string sets/rotates the token,
    an empty string deletes it, and an absent kind is left untouched (so one
    token can be rotated without re-entering the rest). The service validates
    the kinds against the workspace's mode.
    """

    tokens: dict[str, str | None] = Field(
        default_factory=dict,
        description="Map of token-kind slug -> value ('' deletes, absent = untouched).",
    )


class WorkspaceTokensStatus(BaseModel):
    """Which token kinds are configured for a workspace (values never leave the DB)."""

    workspace_id: uuid.UUID
    is_primary: bool
    #: Token-kind slugs that currently have a stored (encrypted) token.
    configured: list[str]


class WorkspaceTokenBundle(BaseModel):
    """Decrypted WB tokens of one workspace, resolved per harvest surface.

    Never serialized into an HTTP response — this DTO exists so the Celery
    harvest can iterate workspaces through the module contract without touching
    repositories directly. Each field is the token the corresponding WB client
    should use, already resolved from the workspace's stored kinds: a primary
    workspace's category token, or (for any other workspace) its single
    ``unified`` token. An empty string means no token is available for that
    surface (that source is then skipped like any failed one).

    One field is not a token. ``internal_features`` says whether this workspace
    belongs to OUR organisation, and it rides along here because the harvest is
    the one caller that has no request and therefore no
    ``OrganizationAccess`` to ask. Sources that only feed an internal-only
    :func:`src.modules.finreports.tasks.harvest.harvest_workspace`.
    """

    workspace_id: uuid.UUID
    name: str
    #: ``True`` when the owning organisation is the primary one. The task-side
    #: twin of ``OrganizationAccess.sees_internal_features``; both answer "is
    #: this us", one for a request and one for a harvest.
    internal_features: bool = False
    content: str = ""
    analytics: str = ""
    advertising: str = ""
    prices: str = ""
    statistics: str = ""
    marketplace: str = ""
