"""Monitoring: the review history — rating snapshots, review state, review events.

Three tables (see src/modules/monitoring/models/reviews.py for why these three
and not a daily copy of every review):

* monitoring.rating_snapshot — one row per card group per day, append-only.
* monitoring.review_state    — one row per review, upserted by the daily walk.
* monitoring.review_event    — what changed about an existing review.

All three carry ``workspace_id``, so they are policed here the way
``row_level_security.sql`` polices every such table, under the same policy name
and expression — a later run of the script converges on it. And all three get
the truncate guard every ``monitoring`` table carries (``f4c8b1e57a29``).

The ``monitoring`` schema's default privileges already grant new tables to the
application role (``least_privilege_role.sql``), so no GRANT is needed here.

Revision ID: e1a7c3f95b20
Revises: c4e8a2f71d39
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e1a7c3f95b20"
down_revision: str | None = "c4e8a2f71d39"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "monitoring"
_TABLES = ("rating_snapshot", "review_state", "review_event")


def upgrade() -> None:
    """Create the tables, then guard and police them."""
    op.create_table(
        "rating_snapshot",
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("imt_id", sa.BigInteger(), nullable=False),
        sa.Column("valuation", sa.Numeric(2, 1), nullable=True),
        sa.Column("valuation_sum", sa.BigInteger(), nullable=False),
        sa.Column("feedback_count", sa.Integer(), nullable=False),
        sa.Column("stars_1", sa.Integer(), nullable=False),
        sa.Column("stars_2", sa.Integer(), nullable=False),
        sa.Column("stars_3", sa.Integer(), nullable=False),
        sa.Column("stars_4", sa.Integer(), nullable=False),
        sa.Column("stars_5", sa.Integer(), nullable=False),
        sa.Column("nm_distribution", postgresql.JSONB(), nullable=True),
        sa.Column("seller_api_count", sa.Integer(), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("snapshot_date", "workspace_id", "imt_id"),
        schema=_SCHEMA,
    )
    op.create_table(
        "review_state",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("imt_id", sa.BigInteger(), nullable=False),
        sa.Column("valuation", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parent_review_id", sa.String(64), nullable=True),
        sa.Column("child_review_id", sa.String(64), nullable=True),
        sa.Column("first_seen_on", sa.Date(), nullable=False),
        sa.Column("last_seen_on", sa.Date(), nullable=False),
        sa.Column("vanished_on", sa.Date(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=True),
        sa.Column("excluded_reasons", sa.String(256), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "review_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_review_state_workspace_imt",
        "review_state",
        ["workspace_id", "imt_id"],
        schema=_SCHEMA,
    )
    op.create_table(
        "review_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("review_id", sa.String(64), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("imt_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("old_valuation", sa.SmallInteger(), nullable=True),
        sa.Column("new_valuation", sa.SmallInteger(), nullable=True),
        sa.Column("detail", sa.String(256), server_default="", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_review_event_workspace_imt_day",
        "review_event",
        ["workspace_id", "imt_id", "observed_on"],
        schema=_SCHEMA,
    )
    for table in _TABLES:
        op.execute(
            "CREATE TRIGGER guard_against_truncate "
            f"BEFORE TRUNCATE ON {_SCHEMA}.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
        )
        op.execute(f"ALTER TABLE {_SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_SCHEMA}.{table} FOR ALL "
            "USING (workspace_id = current_setting('app.workspace_id')::uuid) "
            "WITH CHECK (workspace_id = current_setting('app.workspace_id')::uuid)"
        )


def downgrade() -> None:
    """Drop the tables; their triggers and policies go with them."""
    for table in reversed(_TABLES):
        op.drop_table(table, schema=_SCHEMA)
