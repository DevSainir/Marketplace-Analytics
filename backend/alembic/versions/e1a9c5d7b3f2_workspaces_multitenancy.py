"""workspaces: multi-tenancy (workspaces, encrypted WB tokens, user roles)

Revision ID: e1a9c5d7b3f2
Revises: d5f2a8c1e0b4
Create Date: 2026-07-15

Introduces the workspace tenancy unit:

* ``workspaces.workspaces`` + ``workspaces.workspace_tokens`` (WB tokens now
  live ENCRYPTED in the database, per workspace — no longer in ``.env``).
* Seeds the first workspace "Ivanov Shop" and adopts every existing SKU
  (``monitoring.product_card.workspace_id``) into it.
* One-time token migration: the ``WB_*_TOKEN`` environment variables (if
  still present) are Fernet-encrypted with ``FERNET_SECRET_KEY`` and stored
  for the seed workspace. After this migration the env tokens are unused and
  can be deleted.
* ``auth.users.role`` (``user`` default); grants ``dev`` to the operator
  account ``dev@example.com`` where it exists.
"""

# ruff: noqa: S608 — schema names in the f-string SQL are module constants.
from __future__ import annotations

import uuid

import sqlalchemy as sa
from pydantic_settings import BaseSettings, SettingsConfigDict

from alembic import op
from src.core.ids import uuid7

# revision identifiers, used by Alembic.
revision = "e1a9c5d7b3f2"
down_revision = "d5f2a8c1e0b4"
branch_labels = None
depends_on = None

_WS_SCHEMA = "workspaces"
_MON_SCHEMA = "monitoring"
_AUTH_SCHEMA = "auth"

#: Fixed id for the seed workspace so every environment (local, prod) knows
#: the first workspace under the same identifier.
_SEED_WORKSPACE_ID = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
_SEED_WORKSPACE_NAME = "Ivanov Shop"

#: Operator account granted the ``dev`` role (exists on prod).
_DEV_EMAIL = "dev@example.com"


class _LegacyTokenEnv(BaseSettings):
    """The pre-workspace WB token variables, read exactly as the app used to.

    ``pydantic-settings`` resolves both real environment variables and the
    local ``.env`` file (the application's old lookup order), so the one-time
    migration finds the tokens wherever the deployment kept them. The main
    ``Settings`` class no longer declares these fields — this shim exists only
    inside this migration.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    wb_analytics_token: str = ""
    wb_advertising_token: str = ""
    wb_prices_token: str = ""
    wb_statistics_token: str = ""


def upgrade() -> None:
    """Create workspace tables, seed the first workspace, adopt existing data."""
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_WS_SCHEMA,
    )
    op.create_table(
        "workspace_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey(f"{_WS_SCHEMA}.workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "kind", name="uq_workspace_tokens_workspace_kind"),
        schema=_WS_SCHEMA,
    )
    op.create_index(
        op.f("ix_workspaces_workspace_tokens_workspace_id"),
        "workspace_tokens",
        ["workspace_id"],
        schema=_WS_SCHEMA,
    )

    # --- Seed the first workspace and adopt all existing SKUs into it. ---
    op.execute(
        sa.text(f'INSERT INTO "{_WS_SCHEMA}".workspaces (id, name) VALUES (:id, :name)').bindparams(
            id=_SEED_WORKSPACE_ID, name=_SEED_WORKSPACE_NAME
        )
    )

    op.add_column(
        "product_card",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        schema=_MON_SCHEMA,
    )
    op.create_index(
        op.f("ix_monitoring_product_card_workspace_id"),
        "product_card",
        ["workspace_id"],
        schema=_MON_SCHEMA,
    )
    op.execute(
        sa.text(f'UPDATE "{_MON_SCHEMA}".product_card SET workspace_id = :id').bindparams(
            id=_SEED_WORKSPACE_ID
        )
    )

    # --- Roles: default 'user'; the operator account becomes 'dev'. ---
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=32), nullable=False, server_default="user"),
        schema=_AUTH_SCHEMA,
    )
    op.execute(
        sa.text(
            f"UPDATE \"{_AUTH_SCHEMA}\".users SET role = 'dev' WHERE lower(email) = :email"
        ).bindparams(email=_DEV_EMAIL)
    )

    # --- One-time env -> DB token migration (encrypted at rest). ---
    _migrate_env_tokens()


def _migrate_env_tokens() -> None:
    """Encrypt the legacy ``WB_*_TOKEN`` env values into the seed workspace.

    Runs inside the migration so the very deploy that removes tokens from the
    runtime configuration is the one that persists them encrypted — no window
    where the harvest has no credentials. Skipped silently per-variable when
    the environment no longer carries it (e.g. a fresh checkout after cleanup).

    Raises:
        RuntimeError: If tokens are present but ``FERNET_SECRET_KEY`` is not —
            silently skipping would strand the deployment without credentials.
    """
    legacy = _LegacyTokenEnv()
    tokens: tuple[tuple[str, str], ...] = (
        ("analytics", legacy.wb_analytics_token),
        ("advertising", legacy.wb_advertising_token),
        ("prices", legacy.wb_prices_token),
        ("statistics", legacy.wb_statistics_token),
    )
    present = [(kind, token.strip()) for kind, token in tokens if token.strip()]
    if not present:
        return

    # Imported lazily: the Fernet helper needs FERNET_SECRET_KEY from settings,
    # which is irrelevant for schema-only runs (fresh DBs without env tokens).
    from src.core.security import SecretDecryptionError, encrypt_secret

    for kind, token in present:
        try:
            ciphertext = encrypt_secret(token)
        except SecretDecryptionError as exc:
            raise RuntimeError(
                f"WB_{kind.upper()}_TOKEN is set but cannot be encrypted: {exc} "
                "Set FERNET_SECRET_KEY before migrating."
            ) from exc
        op.execute(
            sa.text(
                f'INSERT INTO "{_WS_SCHEMA}".workspace_tokens '
                "(id, workspace_id, kind, token_encrypted) "
                "VALUES (:id, :workspace_id, :kind, :token)"
            ).bindparams(
                id=uuid7(),
                workspace_id=_SEED_WORKSPACE_ID,
                kind=kind,
                token=ciphertext,
            )
        )


def downgrade() -> None:
    """Drop workspace tables and the adopted columns."""
    op.drop_column("users", "role", schema=_AUTH_SCHEMA)
    op.drop_index(
        op.f("ix_monitoring_product_card_workspace_id"),
        table_name="product_card",
        schema=_MON_SCHEMA,
    )
    op.drop_column("product_card", "workspace_id", schema=_MON_SCHEMA)
    op.drop_index(
        op.f("ix_workspaces_workspace_tokens_workspace_id"),
        table_name="workspace_tokens",
        schema=_WS_SCHEMA,
    )
    op.drop_table("workspace_tokens", schema=_WS_SCHEMA)
    op.drop_table("workspaces", schema=_WS_SCHEMA)
