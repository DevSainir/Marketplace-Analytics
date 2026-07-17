"""sku_day_comment: move free-text notes from the SKU onto one of its days

Revision ID: a2f6b8d0c714
Revises: b7c2e4a9f16d
Create Date: 2026-07-17

Comments used to be one-per-SKU; they are now one-per-SKU-per-day, rendered as
an expandable row of the monitoring matrix (one input per day column). Existing
notes carry no day, so they land on YESTERDAY — the last day whose funnel data
is complete, and the day a note written "about the SKU" most likely described.

The downgrade keeps the newest note per SKU (the old table can hold only one),
so a round-trip is lossy for any SKU commented on more than one day.
"""

from __future__ import annotations

# ruff: noqa: S608 — the schema name in the f-string SQL is a module constant.
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a2f6b8d0c714"
down_revision = "b7c2e4a9f16d"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create ``sku_day_comment``, migrate notes onto yesterday, drop ``sku_comment``."""
    op.create_table(
        "sku_day_comment",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column("comment_date", sa.Date(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.execute(
        f"""
        INSERT INTO {_SCHEMA}.sku_day_comment (nm_id, comment_date, body, updated_at)
        SELECT nm_id, CURRENT_DATE - 1, body, updated_at
        FROM {_SCHEMA}.sku_comment
        """
    )
    op.drop_table("sku_comment", schema=_SCHEMA)


def downgrade() -> None:
    """Recreate ``sku_comment`` with each SKU's newest note; drop the day table."""
    op.create_table(
        "sku_comment",
        sa.Column("nm_id", sa.BigInteger(), primary_key=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.execute(
        f"""
        INSERT INTO {_SCHEMA}.sku_comment (nm_id, body, updated_at)
        SELECT DISTINCT ON (nm_id) nm_id, body, updated_at
        FROM {_SCHEMA}.sku_day_comment
        ORDER BY nm_id, comment_date DESC
        """
    )
    op.drop_table("sku_day_comment", schema=_SCHEMA)
