"""Business logic for the Workspaces module.

Owns the encrypt-on-write / decrypt-on-read discipline for WB tokens: the
service layer is the only place plaintext tokens exist in memory, and only
transiently. Repositories see ciphertext exclusively.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.security import decrypt_secret, encrypt_secret
from src.modules.workspaces.models import CATEGORY_KINDS, TokenKind, Workspace
from src.modules.workspaces.repos import WorkspaceRepository, WorkspaceTokenRepository
from src.modules.workspaces.schemas import (
    WorkspaceRead,
    WorkspaceTokenBundle,
    WorkspaceTokensStatus,
    WorkspaceTokensUpdateRequest,
)

#: Slugs a primary workspace may store (the 13 real WB categories).
_CATEGORY_SLUGS: frozenset[str] = frozenset(kind.value for kind in CATEGORY_KINDS)


def _resolve_bundle(workspace: Workspace, tokens: dict[str, str]) -> WorkspaceTokenBundle:
    """Resolve stored token kinds into the per-surface tokens the harvest needs.

    A primary workspace stores a token per category, so each surface uses its
    own category token. Every other workspace stores a single ``unified``
    token, which is the fallback for every surface. Content falls back to the
    analytics token (historically the WB analytics scope also serves the
    content API) before ``unified``.

    Args:
        workspace: The workspace the tokens belong to (unused directly, but
            keeps the mapping's intent explicit and future-proofs per-mode
            resolution).
        tokens: Decrypted ``{kind slug: token}`` for that workspace.

    Returns:
        A bundle whose fields are the resolved tokens (empty string = none).
    """
    unified = tokens.get(TokenKind.UNIFIED.value, "")

    def pick(*kinds: TokenKind) -> str:
        for kind in kinds:
            value = tokens.get(kind.value)
            if value:
                return value
        return unified

    return WorkspaceTokenBundle(
        workspace_id=workspace.id,
        name=workspace.name,
        content=pick(TokenKind.CONTENT, TokenKind.ANALYTICS),
        analytics=pick(TokenKind.ANALYTICS),
        advertising=pick(TokenKind.PROMOTION),
        prices=pick(TokenKind.PRICES),
        statistics=pick(TokenKind.STATISTICS),
        # No fallback chain: the FBS surface rejects every other category with
        # 401 «token scope not allowed» (verified live 2026-08-13), so guessing
        # a substitute would only turn a skipped source into a failed one.
        marketplace=pick(TokenKind.MARKETPLACE),
    )


class WorkspaceService:
    """Workspace lifecycle and encrypted WB-token management."""

    def __init__(
        self,
        *,
        workspace_repo: WorkspaceRepository,
        token_repo: WorkspaceTokenRepository,
    ) -> None:
        """Store the injected repository collaborators."""
        self._workspaces = workspace_repo
        self._tokens = token_repo

    async def list_workspaces(self) -> list[WorkspaceRead]:
        """Return every workspace (visible to any authenticated user, for now)."""
        return [WorkspaceRead.model_validate(ws) for ws in await self._workspaces.list_all()]

    async def create_workspace(self, *, name: str) -> WorkspaceRead:
        """Create a new workspace with a unique name.

        Args:
            name: The workspace display name.

        Returns:
            The created workspace.

        Raises:
            ConflictError: If a workspace with this name already exists.
        """
        if await self._workspaces.get_by_name(name) is not None:
            raise ConflictError(f"Workspace '{name}' already exists.")
        workspace = await self._workspaces.create(name=name)
        return WorkspaceRead.model_validate(workspace)

    async def delete_workspace(self, workspace_id: uuid.UUID) -> None:
        """Delete a workspace and its stored tokens.

        The workspace's monitoring data is retained but becomes unreachable
        (its SKUs reference a workspace id that no longer resolves).

        Args:
            workspace_id: The workspace to delete.

        Raises:
            NotFoundError: If the workspace does not exist.
        """
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        await self._workspaces.delete(workspace)

    def _allowed_kinds(self, workspace: Workspace) -> frozenset[str]:
        """Token kinds a workspace may store, per its mode.

        Primary workspaces store the 13 real WB categories; every other
        workspace stores a single ``unified`` token used for all of them.

        Args:
            workspace: The target workspace.

        Returns:
            The set of accepted kind slugs.
        """
        return _CATEGORY_SLUGS if workspace.is_primary else frozenset({TokenKind.UNIFIED.value})

    async def set_tokens(
        self,
        workspace_id: uuid.UUID,
        payload: WorkspaceTokensUpdateRequest,
    ) -> WorkspaceTokensStatus:
        """Set/rotate the WB tokens of a workspace (encrypting at rest).

        Only the kinds present in the payload are touched; an empty string
        deletes that kind's stored token. A primary workspace accepts the 13 WB
        categories; any other workspace accepts only ``unified``.

        Args:
            workspace_id: The target workspace.
            payload: Plaintext tokens keyed by kind slug (partial update).

        Returns:
            The resulting configuration status.

        Raises:
            NotFoundError: If the workspace does not exist.
            ValidationError: If a kind is unknown or not allowed for this
                workspace's mode.
        """
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        allowed = self._allowed_kinds(workspace)
        for kind in payload.tokens:
            if kind not in allowed:
                mode = "primary" if workspace.is_primary else "unified-token"
                raise ValidationError(f"Token kind '{kind}' is not valid for a {mode} workspace.")

        for kind, token in payload.tokens.items():
            if token is None:
                continue
            stripped = token.strip()
            if stripped:
                await self._tokens.upsert(
                    workspace_id=workspace_id,
                    kind=kind,
                    token_encrypted=encrypt_secret(stripped),
                )
            else:
                await self._tokens.delete_kind(workspace_id=workspace_id, kind=kind)
        return await self.token_status(workspace_id)

    async def token_status(self, workspace_id: uuid.UUID) -> WorkspaceTokensStatus:
        """Report which token kinds are configured (no values).

        Args:
            workspace_id: The target workspace.

        Returns:
            The workspace mode plus the slugs of configured kinds.

        Raises:
            NotFoundError: If the workspace does not exist.
        """
        workspace = await self._workspaces.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found.")
        configured = sorted(row.kind for row in await self._tokens.list_for_workspace(workspace_id))
        return WorkspaceTokensStatus(
            workspace_id=workspace_id,
            is_primary=workspace.is_primary,
            configured=configured,
        )


async def load_workspace_token_bundle(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceTokenBundle | None:
    """Load and decrypt one workspace's WB tokens (targeted refresh input).

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The workspace whose credentials are needed.

    Returns:
        The decrypted bundle, or ``None`` when the workspace does not exist.

    Raises:
        SecretDecryptionError: If ``FERNET_SECRET_KEY`` cannot decrypt a
            stored token.
    """
    workspace = await WorkspaceRepository(session).get_by_id(workspace_id)
    if workspace is None:
        return None
    rows = await WorkspaceTokenRepository(session).list_for_workspace(workspace_id)
    tokens = {row.kind: decrypt_secret(row.token_encrypted) for row in rows}
    return _resolve_bundle(workspace, tokens)


async def load_workspace_name(session: AsyncSession, workspace_id: uuid.UUID) -> str:
    """Return a workspace's display name (empty string when it does not exist).

    Exposed through ``contract.py`` for modules that need the tenant's legal
    Deliberately does not touch tokens, so no decryption happens.

    Args:
        session: An open async session (caller owns the transaction).
        workspace_id: The workspace to resolve.

    Returns:
        The workspace name, or ``""`` when the workspace is unknown.
    """
    workspace = await WorkspaceRepository(session).get_by_id(workspace_id)
    return workspace.name if workspace is not None else ""


async def load_workspace_token_bundles(session: AsyncSession) -> list[WorkspaceTokenBundle]:
    """Load and decrypt every workspace's WB tokens (harvest fan-out input).

    A module-level function (not a service method) because the Celery harvest
    composes its own session outside the FastAPI DI graph; exposed to other
    modules exclusively via ``contract.py``.

    Args:
        session: An open async session (caller owns the transaction).

    Returns:
        One bundle per workspace, oldest first. Surfaces without a stored
        token are empty strings.

    Raises:
        SecretDecryptionError: If ``FERNET_SECRET_KEY`` cannot decrypt a
            stored token (misconfiguration must fail loudly, not harvest
            nothing silently).
    """
    workspaces = await WorkspaceRepository(session).list_all()
    token_rows = await WorkspaceTokenRepository(session).list_all()
    by_workspace: dict[uuid.UUID, dict[str, str]] = {}
    for row in token_rows:
        by_workspace.setdefault(row.workspace_id, {})[row.kind] = decrypt_secret(
            row.token_encrypted
        )
    return [_resolve_bundle(ws, by_workspace.get(ws.id, {})) for ws in workspaces]
