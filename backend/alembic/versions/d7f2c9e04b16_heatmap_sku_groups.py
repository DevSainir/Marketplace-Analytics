"""Heatmap: the ``heatmap`` schema and its seller-defined article groups.

``heatmap.sku_group`` is a named set of one workspace's articles and
``heatmap.sku_group_item`` its members. Both carry ``workspace_id`` — the item
table too, so it can carry a row-level-security policy of its own.

**This revision grants and polices its own tables**, which no revision before it
did. Until now a new table joined an EXISTING schema, where the default
privileges ``least_privilege_role.sql`` set up already covered it and only the
policy waited for a re-run of ``row_level_security.sql``. A new schema has no
default privileges at all: without a grant here the application role could not
even see it, and every heatmap route would answer 500 until someone re-ran the
script by hand on the box. So, when the application role exists:

* USAGE on the schema, the four DML verbs on its tables, and the same as
  default privileges for tables a later revision adds — exactly what the script
  grants every other schema;
* ROW LEVEL SECURITY on both tables, with the policy the script creates, under
  the same name and expression, so a later run of the script converges on it
  rather than stacking a second one.

Where the role does not exist — a dev box, CI — the grants are skipped, and the
policy is inert because the connecting role owns the tables. Both scripts list
the new schema and tables as well; they remain the source of truth.

Revision ID: d7f2c9e04b16
Revises: c4e1a7b93d20
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d7f2c9e04b16"
down_revision: str | None = "c4e1a7b93d20"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "heatmap"
_TABLES = ("sku_group", "sku_group_item")

_GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marketplace_app') THEN
        GRANT USAGE ON SCHEMA heatmap TO marketplace_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA heatmap
            TO marketplace_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA heatmap TO marketplace_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA heatmap
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marketplace_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA heatmap
            GRANT USAGE, SELECT ON SEQUENCES TO marketplace_app;
    END IF;
END
$$;
"""


def upgrade() -> None:
    """Create the schema and both tables, then grant and police them."""
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}")
    op.create_table(
        "sku_group",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_heatmap_sku_group_workspace_name"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_heatmap_sku_group_workspace_id", "sku_group", ["workspace_id"], schema=_SCHEMA
    )
    op.create_table(
        "sku_group_item",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], [f"{_SCHEMA}.sku_group.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "nm_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_heatmap_sku_group_item_workspace_id",
        "sku_group_item",
        ["workspace_id"],
        schema=_SCHEMA,
    )

    op.execute(_GRANTS)
    for table in _TABLES:
        op.execute(f"ALTER TABLE {_SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_SCHEMA}.{table} FOR ALL "
            "USING (workspace_id = current_setting('app.workspace_id')::uuid) "
            "WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)"
        )


def downgrade() -> None:
    """Drop both tables and the schema; the grants and policies go with them."""
    op.drop_table("sku_group_item", schema=_SCHEMA)
    op.drop_table("sku_group", schema=_SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA}")
