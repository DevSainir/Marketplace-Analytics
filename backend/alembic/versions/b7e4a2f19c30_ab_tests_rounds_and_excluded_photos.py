"""A/B tests: rounds, and photos excluded without being deleted

Revision ID: b7e4a2f19c30
Revises: a3f1c9d20b47
Create Date: 2026-09-08 09:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4a2f19c30"
down_revision: str | None = "a3f1c9d20b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the round a turn belonged to, and the exclusion timestamp.

    Both backfill correctly from their defaults. Every exposure written before
    this ran belonged to the single lap the rotation used to make, which is
    round 1; and no photo could be excluded before there was a way to exclude
    one, so ``NULL`` is the truth for every existing row.
    """
    op.add_column(
        "ab_test_variant_exposure",
        sa.Column("round_number", sa.Integer(), server_default="1", nullable=False),
        schema="ab_tests",
    )
    op.add_column(
        "ab_test_variant",
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        schema="ab_tests",
    )


def downgrade() -> None:
    """Drop both.

    Excluded photos come back into the rotation, because the column that said
    they were out is gone — so a test running across a downgrade starts dealing
    them again on its next pass.
    """
    op.drop_column("ab_test_variant", "excluded_at", schema="ab_tests")
    op.drop_column("ab_test_variant_exposure", "round_number", schema="ab_tests")
