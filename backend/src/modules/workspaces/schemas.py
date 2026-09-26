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
    #: Whether the SKU page renders «Рекламные кластеры» for this кабинет.
    search_clusters_enabled: bool
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
    #: «Финансы». The realization report's home since 2026-09-22: WB switched
    #: off the statistics-surface `reportDetailByPeriod` on 15.07.2026, and its
    #: replacement is `POST /api/finance/v1/sales-reports/*`. Falls back to
    #: ``unified`` like the others; an empty string means this workspace has no
    #: P&L at all, which the harvest reports rather than ignores.
    finance: str = ""
    marketplace: str = ""
    #: The three scopes only the `guide` capture needs. They resolve like every
    #: other surface (own category token, else ``unified``), and an empty string
    #: means that one reference feed is skipped — never that the harvest stops.
    returns: str = ""
    documents: str = ""
    feedbacks: str = ""


class BackfillLaneStatus(BaseModel):
    """One lane of a workspace's history walk, as the profile renders it."""

    lane: str = Field(description="Lane key: catalogue | funnel | advertising | pnl.")
    label: str = Field(description="Russian lane name, rendered verbatim.")
    state: str = Field(description="pending | running | done | failed.")
    done_units: int = Field(description="Units walked so far (days, windows, pages).")
    total_units: int = Field(
        description=(
            "Estimated units in total. An ESTIMATE the lane may revise: a walk that "
            "stops early at WB's retention floor finishes with done < total, so "
            "`state` — never the ratio — is what says the lane is finished."
        )
    )
    percent: int = Field(description="0-100, clamped; 100 whenever the lane is done.")
    message: str = Field(description="Russian status line shown under the lane.")
    updated_at: datetime | None = Field(
        default=None, description="Last tick — a stalled lane is visible by this going stale."
    )


class BackfillStatusResponse(BaseModel):
    """Every lane of one workspace, plus whether anything is still moving."""

    active: bool = Field(
        description="True while any lane is pending or running — what the SPA polls on."
    )
    lanes: list[BackfillLaneStatus]
