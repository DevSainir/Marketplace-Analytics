"""A/B tests: witness the installed photo, and record a conflict

Revision ID: c9d4e1b70f38
Revises: a3f6b2d81c47
Create Date: 2026-09-11 06:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4e1b70f38"
down_revision: str | None = "a3f6b2d81c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give the rotation a way to notice the card was edited under it.

    ``published_at`` on an exposure is the ``Last-Modified`` WB's CDN reported
    once that install had landed — the storefront's own record of when the main
    photo changed. Every later pass compares the card against it, and a
    mismatch means somebody who is not this rotation wrote the photo.

    ``photo_conflict_at`` on the test is when that was found. It is a separate
    column from ``paused_by_ads`` because the two pauses behave oppositely: an
    ads pause promises to resume itself and the sweep keeps that promise, while
    a conflict must wait for a person — a rotation that resumed would overwrite
    the seller's own edit on the next pass.

    Both are nullable with no backfill, and that is the correct value rather
    than a missing one. Exposures that predate this ran were never witnessed;
    inventing a timestamp for them would arm the check against a photo nobody
    observed, and the guard's contract is that not knowing means carrying on.
    Tests already paused get ``NULL``: no conflict was found, because nothing
    was looking.
    """
    op.add_column(
        "ab_test_variant_exposure",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        schema="ab_tests",
    )
    op.add_column(
        "ab_test",
        sa.Column("photo_conflict_at", sa.DateTime(timezone=True), nullable=True),
        schema="ab_tests",
    )


def downgrade() -> None:
    """Drop both columns.

    Losing them costs the rotation its blindness back, not any measurement:
    every window, exposure and count survives.
    """
    op.drop_column("ab_test", "photo_conflict_at", schema="ab_tests")
    op.drop_column("ab_test_variant_exposure", "published_at", schema="ab_tests")
