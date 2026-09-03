"""Count acceptances, now that an invitation is not spent by the first one.

Revision ID: d5e81c37fa90
Revises: c7a2f1b45de8
Create Date: 2026-09-03

An invitation used to be single-use: the first acceptance consumed it and every
later attempt was refused. It is now valid until it expires, and the default
window shrank from seven days to one hour to pay for that — a link anyone can
use is only safe while it is short-lived.

``accepted_at`` and ``accepted_by_user_id`` therefore stop meaning "spent" and
start meaning "last used by", which leaves nothing recording HOW MANY people
came through a link. That is the question an owner now has to be able to ask:
with one use it was implied, with many it is the only way to notice a link that
got out.

Backfilled from the old semantics: a row with ``accepted_at`` set was accepted
exactly once, because under the previous rules it could not have been more.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "d5e81c37fa90"
down_revision = "c7a2f1b45de8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the acceptance counter and seed it from the single-use history."""
    op.add_column(
        "invitations",
        sa.Column("accepted_count", sa.Integer(), nullable=False, server_default="0"),
        schema="organizations",
    )
    op.execute(
        sa.text(
            "UPDATE organizations.invitations SET accepted_count = 1 WHERE accepted_at IS NOT NULL"
        )
    )


def downgrade() -> None:
    """Drop the counter.

    The column is the only thing lost; `accepted_at` still records that a link
    was used at least once, which is exactly what the old single-use model
    tracked.
    """
    op.drop_column("invitations", "accepted_count", schema="organizations")
