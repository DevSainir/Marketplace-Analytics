"""Workspaces: the «Промо-бонусы» switch becomes the workspace's setting.

«Реклама» used to remember the switch per browser. A seller either has WB's
promo bonuses or does not, so the choice is made once for the workspace and
everyone in it sees the same page. On by default, as the per-browser switch
was.

Revision ID: c3a9e5d17f42
Revises: b7e4c2a90d15
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c3a9e5d17f42"
down_revision: str | None = "b7e4c2a90d15"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the switch, on for every workspace."""
    op.add_column(
        "workspaces",
        sa.Column("ads_show_bonus", sa.Boolean(), server_default=sa.true(), nullable=False),
        schema="workspaces",
    )


def downgrade() -> None:
    """Drop the switch; the page falls back to its own default."""
    op.drop_column("workspaces", "ads_show_bonus", schema="workspaces")
