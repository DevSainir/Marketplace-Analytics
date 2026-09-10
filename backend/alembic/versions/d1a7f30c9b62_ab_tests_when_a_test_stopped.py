"""A/B tests: when a test stopped

Revision ID: d1a7f30c9b62
Revises: f4c8b1e57a29
Create Date: 2026-09-10 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a7f30c9b62"
down_revision: str | None = "f4c8b1e57a29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record when the rotation last stopped advancing.

    ``finished_at`` answers this only for a test that ended, and the case where
    the question is actually asked is the paused one: the page has to say since
    when the test has been standing still, and the only clock it had was
    ``updated_at``, which moves on any write.

    Existing rows are back-filled from ``finished_at`` where there is one, so a
    cancelled test reads the same before and after this ran. A test already
    paused gets ``NULL``: nothing recorded when that pause began, and inventing
    a moment for it would be a figure on the screen that no event produced.
    """
    op.add_column(
        "ab_test",
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        schema="ab_tests",
    )
    op.execute("UPDATE ab_tests.ab_test SET stopped_at = finished_at WHERE finished_at IS NOT NULL")


def downgrade() -> None:
    """Drop the column; ``finished_at`` still covers the tests that ended."""
    op.drop_column("ab_test", "stopped_at", schema="ab_tests")
