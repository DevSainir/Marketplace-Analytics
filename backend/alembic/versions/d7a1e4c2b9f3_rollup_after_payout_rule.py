"""Empty the settlement rollup, because one of its columns changed meaning.

``payout_other`` used to add the sales-correction operation; it now subtracts it, the way
WB's own ``forPaySum`` does (``PAYOUT_DEDUCTED_OPERS``). The rollup proves each
day by row count, and a changed formula changes no count — so every day summed
before this revision would go on serving the old figure. Emptying it makes every
day miss once and be rebuilt from the detail on its next read, which is the
arrangement the rollup was designed for: a cold cache costs time, never a wrong
number.

A ``DELETE`` rather than a ``TRUNCATE``: ``finreports`` refuses an unannounced
truncate, and a derived cache is not worth opting out of that guard for.

Nothing to restore on downgrade — the old rows are derivable, and a downgrade
re-derives them the same way.

Revision ID: d7a1e4c2b9f3
Revises: c5e9d2a814f7
Create Date: 2026-09-24
"""

from __future__ import annotations

from alembic import op

revision: str = "d7a1e4c2b9f3"
down_revision: str | None = "c5e9d2a814f7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Drop every rolled-up day so the next read rebuilds it."""
    op.execute("DELETE FROM finreports.settlement_daily_rollup")


def downgrade() -> None:
    """Same: the cache is rebuilt under whichever formula is deployed."""
    op.execute("DELETE FROM finreports.settlement_daily_rollup")
