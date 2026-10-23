"""Monitoring: WB's subject (category) and brand on the catalogue card.

The heatmap filters by category and cuts its rows by category or brand, and the
settlement — the only place either name was stored until now — carries them
only for articles that have sold. The Content API returns both on every card,
so the catalogue sync starts keeping them here.

Existing rows get ``""`` and are filled by the next catalogue sync.

Revision ID: c4e1a7b93d20
Revises: a8e3d5f19c62
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c4e1a7b93d20"
down_revision: str | None = "a8e3d5f19c62"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add the two name columns, empty for every existing card."""
    op.add_column(
        "product_card",
        sa.Column("subject_name", sa.String(128), server_default="", nullable=False),
        schema=_SCHEMA,
    )
    op.add_column(
        "product_card",
        sa.Column("brand", sa.String(128), server_default="", nullable=False),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop both columns."""
    op.drop_column("product_card", "brand", schema=_SCHEMA)
    op.drop_column("product_card", "subject_name", schema=_SCHEMA)
