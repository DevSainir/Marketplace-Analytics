"""A/B tests: pause with the advertising

Revision ID: c4d9e6b13a72
Revises: b7e4a2f19c30
Create Date: 2026-09-08 14:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d9e6b13a72"
down_revision: str | None = "b7e4a2f19c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record whether a pause was the rotation's doing or the seller's.

    ``false`` is right for every existing row: until this ran, the only way a
    test could be paused was by hand, so nothing already paused should start
    resuming itself when a campaign comes back.
    """
    op.add_column(
        "ab_test",
        sa.Column("paused_by_ads", sa.Boolean(), server_default="false", nullable=False),
        schema="ab_tests",
    )


def downgrade() -> None:
    """Drop the flag.

    Tests the rotation paused stay paused, because the column that would have
    told the poller to pick them up again is gone. The seller can start them by
    hand, which is what they had to do before this existed.
    """
    op.drop_column("ab_test", "paused_by_ads", schema="ab_tests")
