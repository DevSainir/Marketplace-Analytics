"""sku_day_action_history: who changed a «Действия» row, and from what

Revision ID: d7b3e1a95c20
Revises: b5d3e8a61f90
Create Date: 2026-10-10

``sku_day_action`` keeps only the last state of a day. This adds an
append-only log of every save that changed it — the account, the moment, and
the answers before and after — so a disputed or misplaced entry can be traced
from the database instead of reconstructed from request logs and a backup.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "d7b3e1a95c20"
down_revision = "b5d3e8a61f90"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"
_TABLE = "sku_day_action_history"

#: The guard installed by ``f4c8b1e57a29``: a history that a stray TRUNCATE
#: could empty without a trace would defeat its one purpose.
_TRUNCATE_TRIGGER = "guard_against_truncate"


def upgrade() -> None:
    """Create ``sku_day_action_history``."""
    op.create_table(
        "sku_day_action_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_sku_day_action_history_sku_day",
        "sku_day_action_history",
        ["nm_id", "action_date"],
        schema=_SCHEMA,
    )
    op.execute(
        f"CREATE TRIGGER {_TRUNCATE_TRIGGER} BEFORE TRUNCATE ON {_SCHEMA}.{_TABLE} "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )


def downgrade() -> None:
    """Drop ``sku_day_action_history``."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRUNCATE_TRIGGER} ON {_SCHEMA}.{_TABLE}")
    op.drop_index(
        "ix_sku_day_action_history_sku_day",
        table_name="sku_day_action_history",
        schema=_SCHEMA,
    )
    op.drop_table("sku_day_action_history", schema=_SCHEMA)
