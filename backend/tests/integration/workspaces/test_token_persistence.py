"""Integration tests for WB-token storage against a real PostgreSQL.

Three things can only be proved with a real database here:

* the ciphertext genuinely lands in the column (a raw SQL read, bypassing the
  ORM, so no mapper hook can be masking it);
* the ``(workspace_id, kind)`` unique constraint makes ``upsert`` a rotation
  rather than a second row;
* the contract functions the Celery harvest calls — which take a raw session,
  not a service — return correctly resolved bundles, and drop the tenants whose
  subscription has run out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import encrypt_secret
from src.modules.organizations.models import Organization
from src.modules.organizations.repos import SubscriptionRepository
from src.modules.workspaces.contract import (
    load_workspace_token_bundle,
    load_workspace_token_bundles,
)
from src.modules.workspaces.models import TokenKind, Workspace, WorkspaceToken
from src.modules.workspaces.repos import WorkspaceTokenRepository

WB_TOKEN = "eyJhbGciOiJFUzI1NiJ9.a-real-looking-wb-bearer-token"


@pytest.fixture(autouse=True)
def _fernet_key(settings_override):
    """Give the module a real, disposable encryption key."""
    with settings_override(fernet_secret_key=Fernet.generate_key().decode()):
        yield


@pytest.fixture
async def primary(db_session: AsyncSession, organization: Organization) -> Workspace:
    """A persisted primary workspace (one token per WB category)."""
    workspace = Workspace(organization_id=organization.id, name="Demo Shop", is_primary=True)
    db_session.add(workspace)
    await db_session.flush()
    return workspace


@pytest.fixture
async def secondary(db_session: AsyncSession, organization: Organization) -> Workspace:
    """A persisted non-primary workspace (single ``unified`` token)."""
    workspace = Workspace(organization_id=organization.id, name="ООО Второй", is_primary=False)
    db_session.add(workspace)
    await db_session.flush()
    return workspace


async def test_the_column_holds_ciphertext_not_the_token(
    db_session: AsyncSession, secondary: Workspace
) -> None:
    """Read the raw column: a database dump must never expose a WB credential.

    Deliberately bypasses the ORM — an ORM-level read could be intercepted by a
    type decorator and would not prove what is actually on disk.
    """
    await WorkspaceTokenRepository(db_session).upsert(
        workspace_id=secondary.id,
        kind=TokenKind.UNIFIED.value,
        token_encrypted=encrypt_secret(WB_TOKEN),
    )
    await db_session.flush()

    raw = (
        await db_session.execute(
            sa.text(
                "SELECT token_encrypted FROM workspaces.workspace_tokens WHERE workspace_id = :ws"
            ),
            {"ws": secondary.id},
        )
    ).scalar_one()

    assert raw != WB_TOKEN
    assert WB_TOKEN not in raw
    assert raw.startswith("gAAAAA")  # Fernet's version byte, base64-encoded


async def test_rotating_a_token_replaces_the_row(
    db_session: AsyncSession, secondary: Workspace
) -> None:
    """The ``(workspace_id, kind)`` constraint makes upsert a true rotation.

    A second row would leave the old credential live and make the resolved
    bundle depend on row order.
    """
    repo = WorkspaceTokenRepository(db_session)
    await repo.upsert(
        workspace_id=secondary.id,
        kind=TokenKind.UNIFIED.value,
        token_encrypted=encrypt_secret("v1"),
    )
    await repo.upsert(
        workspace_id=secondary.id,
        kind=TokenKind.UNIFIED.value,
        token_encrypted=encrypt_secret("v2"),
    )
    await db_session.flush()

    rows = await repo.list_for_workspace(secondary.id)

    assert len(rows) == 1
    bundle = await load_workspace_token_bundle(db_session, secondary.id)
    assert bundle is not None
    assert bundle.analytics == "v2"


async def test_deleting_a_workspace_deletes_its_tokens(
    db_session: AsyncSession, secondary: Workspace
) -> None:
    """The FK cascade must not leave orphaned credentials behind.

    An orphaned ciphertext row is a live WB credential with no owner and no UI
    that can rotate it.
    """
    await WorkspaceTokenRepository(db_session).upsert(
        workspace_id=secondary.id,
        kind=TokenKind.UNIFIED.value,
        token_encrypted=encrypt_secret(WB_TOKEN),
    )
    await db_session.flush()

    await db_session.delete(secondary)
    await db_session.flush()

    remaining = (await db_session.execute(sa.select(WorkspaceToken))).scalars().all()
    assert remaining == []


async def test_the_harvest_bundle_resolves_every_surface(
    db_session: AsyncSession, primary: Workspace
) -> None:
    """The contract function the Celery harvest calls returns usable tokens."""
    repo = WorkspaceTokenRepository(db_session)
    for kind, value in (
        (TokenKind.CONTENT, "content-t"),
        (TokenKind.ANALYTICS, "analytics-t"),
        (TokenKind.PROMOTION, "promo-t"),
        (TokenKind.PRICES, "prices-t"),
        (TokenKind.STATISTICS, "stats-t"),
    ):
        await repo.upsert(
            workspace_id=primary.id, kind=kind.value, token_encrypted=encrypt_secret(value)
        )
    await db_session.flush()

    bundle = await load_workspace_token_bundle(db_session, primary.id)

    assert bundle is not None
    assert (bundle.content, bundle.analytics, bundle.advertising) == (
        "content-t",
        "analytics-t",
        "promo-t",
    )
    assert (bundle.prices, bundle.statistics) == ("prices-t", "stats-t")


async def test_the_fan_out_returns_one_bundle_per_workspace(
    db_session: AsyncSession, primary: Workspace, secondary: Workspace
) -> None:
    """The harvest iterates every tenant, including ones with no credentials.

    A workspace missing from this list is a tenant that silently stops being
    harvested.
    """
    await WorkspaceTokenRepository(db_session).upsert(
        workspace_id=secondary.id,
        kind=TokenKind.UNIFIED.value,
        token_encrypted=encrypt_secret("unified-t"),
    )
    await db_session.flush()

    bundles = await load_workspace_token_bundles(db_session)

    by_id = {bundle.workspace_id: bundle for bundle in bundles}
    assert {primary.id, secondary.id} <= set(by_id)
    assert by_id[secondary.id].prices == "unified-t"
    assert by_id[primary.id].prices == ""


async def test_the_fan_out_drops_a_tenant_whose_term_ran_out(
    db_session: AsyncSession, secondary: Workspace, organization: Organization
) -> None:
    """The paywall reaches the schedule here, and nowhere else.

    Every fleet-wide harvest starts from this one call, so a tenant past its
    grace window stops costing WB budget in one place rather than in each task.
    Asserted against a real database because the join it rests on — workspace →
    organisation → subscription — is the part a pure unit test cannot prove.
    """
    subscription = await SubscriptionRepository(db_session).get_for_organization(organization.id)
    assert subscription is not None
    # Past expiry AND past the three grace days.
    subscription.expires_at = datetime.now(UTC) - timedelta(days=10)
    await db_session.flush()

    bundles = await load_workspace_token_bundles(db_session)

    assert [bundle.workspace_id for bundle in bundles] == []


async def test_the_fan_out_still_harvests_inside_the_grace_window(
    db_session: AsyncSession, secondary: Workspace, organization: Organization
) -> None:
    """A lapsed term still harvests while its grace days last.

    The gap WB leaves is not backfillable, so stopping a harvest during the days
    a bank transfer is clearing would punch a permanent hole in the data of a
    customer who did pay.
    """
    subscription = await SubscriptionRepository(db_session).get_for_organization(organization.id)
    assert subscription is not None
    subscription.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.flush()

    bundles = await load_workspace_token_bundles(db_session)

    assert [bundle.workspace_id for bundle in bundles] == [secondary.id]


async def test_an_unknown_workspace_yields_no_bundle(db_session: AsyncSession) -> None:
    """A deleted workspace resolves to ``None``, not an empty-token bundle.

    An empty bundle would make the harvest run against WB with no credentials
    and record the resulting failures as real data gaps.
    """
    import uuid

    assert await load_workspace_token_bundle(db_session, uuid.uuid4()) is None
