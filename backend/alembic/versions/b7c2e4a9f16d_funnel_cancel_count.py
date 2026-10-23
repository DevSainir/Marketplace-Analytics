"""funnel_cancel_count: store the cohort's cancelled (refused) deliveries

Revision ID: b7c2e4a9f16d
Revises: a3d1f7b52c68
Create Date: 2026-07-16

The buyout rate is WB's ``buyoutCount / (buyoutCount + cancelCount)``. The
daily funnel-history feed serves ``buyoutCount`` and a whole-number
``buyoutPercent`` but NO cancel count, so the metric used to reverse-engineer
the denominator as ``buyout_count / buyoutPercent``. That is wrong twice over:
a cohort with zero buyouts reports ``buyoutPercent = 0`` and carries no
recoverable denominator at all (its refusals silently vanished from the
average), and the integer percent makes the recovered denominator noisy at low
counts.

``cancel_count`` is therefore fetched from the period-aggregate endpoint, which
serves the real ``cancelCount``. It is NULLABLE on purpose: NULL means "this
cohort has not been refreshed from the aggregate yet" and is excluded from the
average, which keeps a not-yet-backfilled day rendering «—» instead of a
fabricated 100% (``buyouts / (buyouts + 0)``).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c2e4a9f16d"
down_revision = "a3d1f7b52c68"
branch_labels = None
depends_on = None

_SCHEMA = "monitoring"


def upgrade() -> None:
    """Add the nullable ``cancel_count`` cohort column."""
    op.add_column(
        "sales_funnel_daily",
        sa.Column("cancel_count", sa.Integer(), nullable=True),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop ``cancel_count``."""
    op.drop_column("sales_funnel_daily", "cancel_count", schema=_SCHEMA)
