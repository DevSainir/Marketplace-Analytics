"""matrix_override: manual metrics-matrix cell edits

Backs the spreadsheet-style editing of the daily metrics matrix. Manager edits
are resolved to input facts and stored here as a thin overlay over the pristine
WB fact tables (never overwritten). One row per overridden input field
``(nm_id, stat_date, bucket, field)``; any WB refresh clears a SKU's rows.

Revision ID: a1c7e2f9b304
Revises: f3b9c4d17e5a
Create Date: 2026-07-11 09:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c7e2f9b304"
down_revision: str | None = "f3b9c4d17e5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Create the ``matrix_override`` overlay table."""
    op.create_table(
        "matrix_override",
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("bucket", sa.String(length=16), nullable=False),
        sa.Column("field", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("nm_id", "stat_date", "bucket", "field"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the ``matrix_override`` table."""
    op.drop_table("matrix_override", schema=_SCHEMA)
