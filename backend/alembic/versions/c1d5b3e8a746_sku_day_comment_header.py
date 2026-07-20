"""sku_day_comment: add the per-day header carried across the day boundary

Revision ID: c1d5b3e8a746
Revises: b9e4f2a7c3d1
Create Date: 2026-07-20

A day's note gains a second field: a short header above the free-text comment.
The comment stays purely per-day; the header is copied onto each new day by
``monitoring.carry_day_headers`` so a running title continues without retyping.

``body`` becomes NOT NULL DEFAULT '' so a header-only day is representable
(previously every row had to carry comment text).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d5b3e8a746"
down_revision = "b9e4f2a7c3d1"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add ``header`` and give ``body`` an empty-string default."""
    op.add_column(
        "sku_day_comment",
        sa.Column("header", sa.Text(), nullable=False, server_default=""),
        schema=_SCHEMA,
    )
    op.alter_column(
        "sku_day_comment",
        "body",
        existing_type=sa.Text(),
        nullable=False,
        server_default="",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop ``header``, and the rows that only ever had one.

    A header-only row has no comment to fall back on, so keeping it would
    leave a blank note behind; the older schema has no place for it.
    """
    op.execute(f"DELETE FROM {_SCHEMA}.sku_day_comment WHERE body = ''")  # noqa: S608
    op.drop_column("sku_day_comment", "header", schema=_SCHEMA)
    op.alter_column(
        "sku_day_comment",
        "body",
        existing_type=sa.Text(),
        nullable=False,
        server_default=None,
        schema=_SCHEMA,
    )
