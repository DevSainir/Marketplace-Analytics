"""Workspace backfill: per-lane progress and resume cursor

Revision ID: a3f6b2d81c47
Revises: d1a7f30c9b62
Create Date: 2026-09-10 13:40:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f6b2d81c47"
down_revision: str | None = "d1a7f30c9b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """One row per (workspace, lane): how far its history walk has got.

    Progress lives in Postgres rather than in Celery's result backend — which
    is where "Refresh all SKUs" keeps its own — because the two have different
    lifetimes. That refresh is over in minutes and its task id is still in the
    SPA's hand when it finishes. A backfill's P&L lane runs for sixteen hours
    on a large account, outliving the tab, the worker and any result TTL.

    ``cursor`` is the same row rather than a second table: "how far along are
    we" and "where do we resume" are one fact, and a resumed walk that reports
    the previous run's progress is what keeping them apart produces.

    No backfill exists for workspaces created before this ran, and none is
    invented: they get no rows, and the profile reads that as "nothing is
    running", which is true.
    """
    op.create_table(
        "workspace_backfill",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("done_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("message", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspaces.id"],
            name="fk_workspace_backfill_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "lane", name="pk_workspace_backfill"),
        schema="workspaces",
    )


def downgrade() -> None:
    """Drop the table. Losing it costs a backfill its resume point, not data."""
    op.drop_table("workspace_backfill", schema="workspaces")
