"""Organizations: an activation code carries the кабинет and manager caps it sells.

Until now every redeemed code started an unlimited subscription, because the
code had nowhere to say otherwise. Both columns are nullable and ``NULL`` means
unlimited, so every code already issued keeps meaning exactly what it did.

Revision ID: a6d3f08c2e71
Revises: e1a7c3f95b20
Create Date: 2026-10-02
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a6d3f08c2e71"
down_revision: str | None = "e1a7c3f95b20"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "organizations"


def upgrade() -> None:
    """Add the two caps."""
    op.add_column(
        "activation_codes", sa.Column("max_workspaces", sa.Integer(), nullable=True), schema=_SCHEMA
    )
    op.add_column(
        "activation_codes", sa.Column("max_managers", sa.Integer(), nullable=True), schema=_SCHEMA
    )


def downgrade() -> None:
    """Drop them."""
    op.drop_column("activation_codes", "max_managers", schema=_SCHEMA)
    op.drop_column("activation_codes", "max_workspaces", schema=_SCHEMA)
