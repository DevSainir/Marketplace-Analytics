"""widen matrix_override.field for display-override cell keys

Revision ID: c4e8f1a9d3b2
Revises: a1d7e5c2b9f8
Create Date: 2026-07-15

Display overrides store the target cell as ``field = "<bucket>:<metric>"``
(e.g. ``"manual_catalog:order_conversion"``), which exceeds the original
16-char width. Widen to 48. Purely a column-type widening — no data change.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4e8f1a9d3b2"
down_revision = "a1d7e5c2b9f8"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Widen ``matrix_override.field`` from VARCHAR(16) to VARCHAR(48)."""
    op.alter_column(
        "matrix_override",
        "field",
        existing_type=sa.String(length=16),
        type_=sa.String(length=48),
        existing_nullable=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Narrow ``matrix_override.field`` back to VARCHAR(16).

    Display-override rows (``bucket = 'cell'``) can exceed 16 chars, so drop
    them first to avoid a truncation error on the way down.
    """

    op.execute(f"DELETE FROM {_SCHEMA}.matrix_override WHERE bucket = 'cell'")  # noqa: S608
    op.alter_column(
        "matrix_override",
        "field",
        existing_type=sa.String(length=48),
        type_=sa.String(length=16),
        existing_nullable=False,
        schema=_SCHEMA,
    )
