"""Heatmap: ``heatmap.sku_norm``, a seller's own norm per article and metric.

The table joins the EXISTING ``heatmap`` schema, whose default privileges
(set by ``d7f2c9e04b16``) already grant it to the application role — so only
row-level security is switched on here, with the same policy, under the same
name and expression, as ``row_level_security.sql`` creates; a later run of the
script converges on it.

Revision ID: a9d4f2c7e815
Revises: b2e6d0a93c14
Create Date: 2026-09-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a9d4f2c7e815"
down_revision: str | None = "b2e6d0a93c14"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "heatmap"


def upgrade() -> None:
    """Create the table, then police it."""
    op.create_table(
        "sku_norm",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "nm_id", "metric", name="uq_heatmap_sku_norm_workspace_nm_metric"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_heatmap_sku_norm_workspace_id", "sku_norm", ["workspace_id"], schema=_SCHEMA
    )
    op.execute(f"ALTER TABLE {_SCHEMA}.sku_norm ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_SCHEMA}.sku_norm FOR ALL "
        "USING (workspace_id = current_setting('app.workspace_id')::uuid) "
        "WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)"
    )


def downgrade() -> None:
    """Drop the table; its policy goes with it."""
    op.drop_table("sku_norm", schema=_SCHEMA)
