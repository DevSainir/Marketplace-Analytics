"""Empty the settlement rollup again: ``payout_other`` changed meaning twice.

``d7a1e4c2b9f3`` emptied it when the sales-correction operation started being subtracted by
name. That rule was wrong: WB puts the direction in ``doc_type_name`` and the
same operation arrives under both document types, so the column now negates the
refund rows whatever their operation (``REFUND_DOC_TYPE``). Any day rebuilt
under the short-lived rule holds the wrong figure with the right row count, and
the rollup proves days by count alone — so it is emptied once more and every
day is rebuilt from the detail on its next read.

Revision ID: e4b8c1f07a2d
Revises: d7a1e4c2b9f3
Create Date: 2026-09-24
"""

from __future__ import annotations

from alembic import op

revision: str = "e4b8c1f07a2d"
down_revision: str | None = "d7a1e4c2b9f3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Drop every rolled-up day so the next read rebuilds it."""
    op.execute("DELETE FROM finreports.settlement_daily_rollup")


def downgrade() -> None:
    """Same: the cache is rebuilt under whichever formula is deployed."""
    op.execute("DELETE FROM finreports.settlement_daily_rollup")
