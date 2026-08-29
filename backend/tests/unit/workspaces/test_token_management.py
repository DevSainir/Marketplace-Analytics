"""Unit tests for workspace WB-token storage and per-surface resolution.

Two behaviours matter here and neither is obvious from the code:

* **Encrypt on write, never echo.** The repository must only ever see Fernet
  ciphertext, and the response DTO reports *which* surfaces are configured —
  never a token value.
* **Mode-dependent resolution.** The primary workspace stores one token per WB
  category; every other workspace stores a single ``unified`` token reused for
  all surfaces. Getting this wrong makes a harvest silently run with no
  credentials for some sources.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.core.security import decrypt_secret
from src.modules.workspaces.models import TokenKind
from src.modules.workspaces.schemas import WorkspaceTokensUpdateRequest
from src.modules.workspaces.services import WorkspaceService, _resolve_bundle
from tests.support.fakes import (
    FakeWorkspaceRepository,
    FakeWorkspaceTokenRepository,
    make_workspace,
)

#: The tenant every workspace in this module belongs to. One organisation is
#: enough here: these tests are about token ENCRYPTION and per-mode kind rules,
#: and the cross-tenant refusals are proved at the route tier where the guard is.
ORG_ID = uuid.UUID("018f4e2a-0000-7000-8000-0000000000aa")


@pytest.fixture(autouse=True)
def _fernet_key(settings_override):
    """Give the whole module a real, disposable encryption key."""
    with settings_override(fernet_secret_key=Fernet.generate_key().decode()):
        yield


def _service(
    workspaces: FakeWorkspaceRepository, tokens: FakeWorkspaceTokenRepository
) -> WorkspaceService:
    """Build a WorkspaceService over in-memory repositories."""
    return WorkspaceService(workspace_repo=workspaces, token_repo=tokens)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
async def test_workspace_names_are_unique() -> None:
    """Creating a second workspace with an existing name is a conflict."""
    existing = make_workspace(organization_id=ORG_ID, name="ИП Иванов")
    service = _service(FakeWorkspaceRepository([existing]), FakeWorkspaceTokenRepository())

    with pytest.raises(ConflictError):
        await service.create_workspace(organization_id=ORG_ID, name="ИП Иванов")


async def test_new_workspaces_are_never_primary() -> None:
    """Only the seeded workspace is primary; new ones use a unified token."""
    service = _service(FakeWorkspaceRepository(), FakeWorkspaceTokenRepository())

    created = await service.create_workspace(organization_id=ORG_ID, name="ООО Новый")

    assert created.is_primary is False


async def test_deleting_an_unknown_workspace_is_not_found() -> None:
    """A stale id from a client that still has it selected yields 404, not 500."""
    service = _service(FakeWorkspaceRepository(), FakeWorkspaceTokenRepository())

    with pytest.raises(NotFoundError):
        await service.delete_workspace(
            make_workspace(organization_id=ORG_ID).id, organization_id=ORG_ID
        )


# --------------------------------------------------------------------------- #
# Token storage
# --------------------------------------------------------------------------- #
async def test_token_is_encrypted_before_it_reaches_the_repository() -> None:
    """Persistence sees ciphertext only — the plaintext WB token never lands."""
    workspace = make_workspace(organization_id=ORG_ID)
    tokens = FakeWorkspaceTokenRepository()
    service = _service(FakeWorkspaceRepository([workspace]), tokens)
    secret = "eyJhbGciOiJFUzI1NiJ9.real-wb-token"

    await service.set_tokens(
        workspace.id,
        WorkspaceTokensUpdateRequest(tokens={"unified": secret}),
        organization_id=ORG_ID,
    )

    stored = tokens.rows[(workspace.id, "unified")]
    assert stored.token_encrypted != secret
    assert decrypt_secret(stored.token_encrypted) == secret


async def test_status_reports_configured_kinds_without_values() -> None:
    """The response says *which* surfaces are set, never *what* they are set to."""
    workspace = make_workspace(organization_id=ORG_ID)
    service = _service(FakeWorkspaceRepository([workspace]), FakeWorkspaceTokenRepository())

    status = await service.set_tokens(
        workspace.id,
        WorkspaceTokensUpdateRequest(tokens={"unified": "a-token"}),
        organization_id=ORG_ID,
    )

    assert status.configured == ["unified"]
    assert "a-token" not in status.model_dump_json()


async def test_absent_kinds_are_left_untouched() -> None:
    """A partial update rotates one token without re-entering the others.

    The admin form submits only what changed; treating absence as deletion
    would wipe a workspace's credentials on every save.
    """
    workspace = make_workspace(organization_id=ORG_ID, name="ИП Демо", is_primary=True)
    tokens = FakeWorkspaceTokenRepository()
    service = _service(FakeWorkspaceRepository([workspace]), tokens)
    await service.set_tokens(
        workspace.id,
        WorkspaceTokensUpdateRequest(tokens={"content": "content-token", "prices": "price-token"}),
        organization_id=ORG_ID,
    )

    status = await service.set_tokens(
        workspace.id,
        WorkspaceTokensUpdateRequest(tokens={"content": "rotated-token"}),
        organization_id=ORG_ID,
    )

    assert status.configured == ["content", "prices"]
    assert decrypt_secret(tokens.rows[(workspace.id, "content")].token_encrypted) == "rotated-token"
    assert decrypt_secret(tokens.rows[(workspace.id, "prices")].token_encrypted) == "price-token"


async def test_empty_string_deletes_a_stored_token() -> None:
    """Clearing the field in the admin form removes the credential."""
    workspace = make_workspace(organization_id=ORG_ID)
    tokens = FakeWorkspaceTokenRepository()
    service = _service(FakeWorkspaceRepository([workspace]), tokens)
    await service.set_tokens(
        workspace.id,
        WorkspaceTokensUpdateRequest(tokens={"unified": "a-token"}),
        organization_id=ORG_ID,
    )

    status = await service.set_tokens(
        workspace.id, WorkspaceTokensUpdateRequest(tokens={"unified": ""}), organization_id=ORG_ID
    )

    assert status.configured == []
    assert (workspace.id, "unified") not in tokens.rows


async def test_non_primary_workspace_rejects_category_kinds() -> None:
    """A unified-token workspace may not store per-category tokens."""
    workspace = make_workspace(organization_id=ORG_ID, is_primary=False)
    service = _service(FakeWorkspaceRepository([workspace]), FakeWorkspaceTokenRepository())

    with pytest.raises(ValidationError, match="unified-token"):
        await service.set_tokens(
            workspace.id,
            WorkspaceTokensUpdateRequest(tokens={"content": "a-token"}),
            organization_id=ORG_ID,
        )


async def test_primary_workspace_rejects_the_unified_kind() -> None:
    """The primary workspace is granular; ``unified`` is not one of its kinds."""
    workspace = make_workspace(organization_id=ORG_ID, is_primary=True)
    service = _service(FakeWorkspaceRepository([workspace]), FakeWorkspaceTokenRepository())

    with pytest.raises(ValidationError, match="primary"):
        await service.set_tokens(
            workspace.id,
            WorkspaceTokensUpdateRequest(tokens={"unified": "a-token"}),
            organization_id=ORG_ID,
        )


async def test_unknown_kind_is_rejected_before_anything_is_written() -> None:
    """Validation runs over the whole payload first — no partial application.

    A payload of {valid, invalid} must write neither, or a failed request would
    leave half a rotation applied.
    """
    workspace = make_workspace(organization_id=ORG_ID, is_primary=True)
    tokens = FakeWorkspaceTokenRepository()
    service = _service(FakeWorkspaceRepository([workspace]), tokens)

    with pytest.raises(ValidationError):
        await service.set_tokens(
            workspace.id,
            WorkspaceTokensUpdateRequest(tokens={"content": "good", "telepathy": "bogus"}),
            organization_id=ORG_ID,
        )

    assert tokens.rows == {}


# --------------------------------------------------------------------------- #
# Per-surface resolution (the harvest's input)
# --------------------------------------------------------------------------- #
def test_unified_token_serves_every_surface() -> None:
    """One token on a non-primary workspace authenticates all five surfaces."""
    workspace = make_workspace(organization_id=ORG_ID, is_primary=False)

    bundle = _resolve_bundle(workspace, {TokenKind.UNIFIED.value: "one-token"})

    assert bundle.content == "one-token"
    assert bundle.analytics == "one-token"
    assert bundle.advertising == "one-token"
    assert bundle.prices == "one-token"
    assert bundle.statistics == "one-token"


def test_the_marketplace_surface_does_not_take_the_unified_token() -> None:
    """FBS is opt-in per workspace, even for a workspace whose token allows it.

    The enabled FBS warehouse belongs to one WB account. A unified token from
    another workspace authenticates and then 404s on a warehouse that is not
    its own — which is exactly what three workspaces did on the 2026-08-14
    harvest, each reporting a withheld source that was never theirs to fetch.
    """
    workspace = make_workspace(organization_id=ORG_ID, is_primary=False)

    bundle = _resolve_bundle(workspace, {TokenKind.UNIFIED.value: "one-token"})

    assert bundle.marketplace == ""


def test_category_tokens_map_to_their_own_surfaces() -> None:
    """A primary workspace routes each WB category token to its own client."""
    workspace = make_workspace(organization_id=ORG_ID, is_primary=True)

    bundle = _resolve_bundle(
        workspace,
        {
            TokenKind.CONTENT.value: "content-t",
            TokenKind.ANALYTICS.value: "analytics-t",
            TokenKind.PROMOTION.value: "promo-t",
            TokenKind.PRICES.value: "prices-t",
            TokenKind.STATISTICS.value: "stats-t",
        },
    )

    assert bundle.content == "content-t"
    assert bundle.analytics == "analytics-t"
    assert bundle.advertising == "promo-t"
    assert bundle.prices == "prices-t"
    assert bundle.statistics == "stats-t"


def test_content_falls_back_to_the_analytics_token() -> None:
    """Historically the WB analytics scope also served the content API.

    A workspace configured before the content category existed must keep
    harvesting cards rather than silently losing that source.
    """
    workspace = make_workspace(organization_id=ORG_ID, is_primary=True)

    bundle = _resolve_bundle(workspace, {TokenKind.ANALYTICS.value: "analytics-t"})

    assert bundle.content == "analytics-t"


def test_missing_surface_resolves_to_an_empty_token() -> None:
    """An unconfigured surface yields "", which the harvest skips like a failure.

    Returning ``None`` would crash the client constructor instead.
    """
    workspace = make_workspace(organization_id=ORG_ID, is_primary=True)

    bundle = _resolve_bundle(workspace, {})

    assert bundle.prices == ""
    assert bundle.statistics == ""
