"""A/B tests: the card's own photo rotates too

Revision ID: a3f1c9d20b47
Revises: 9de6f1cb3256
Create Date: 2026-09-07 12:40:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f1c9d20b47"
down_revision: str | None = "9de6f1cb3256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Mark which variant is the card's own photo rather than an upload.

    Every existing row is an upload, so ``false`` is both the default and the
    truth for the backfill — no data migration is needed. Tests already running
    at deploy time keep the rotation they started with: the capture happens at
    start, and theirs has been and gone.
    """
    op.add_column(
        "ab_test_variant",
        sa.Column("is_original", sa.Boolean(), server_default="false", nullable=False),
        schema="ab_tests",
    )


def downgrade() -> None:
    """Drop the flag.

    The captured photo's row survives as an ordinary variant at position 0,
    which the rotation still walks first. Downgrading loses the label, not the
    photo — and the SPA falls back to «Вариант 0» for it.
    """
    op.drop_column("ab_test_variant", "is_original", schema="ab_tests")
