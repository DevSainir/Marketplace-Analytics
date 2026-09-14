"""Record where each refresh token was minted, so sessions can be listed.

A refresh-token family IS a session — one login lineage, rotated every fifteen
minutes for as long as the browser stays alive. The rows carried no sign of
which browser that was, so the only thing an account holder could be offered was
"sign out everywhere": a lever with no way to aim it. Naming the device is what
turns that into "this phone is not mine, end it".

Both columns are nullable and stay nullable. Every row written before this
migration has no answer, and back-filling a guess would put a fiction into the
list somebody uses to decide whether they have been broken into.

Revision ID: a1c73e95b204
Revises: b6d92f4a71c8
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "a1c73e95b204"
down_revision: str | None = "b6d92f4a71c8"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the provenance columns to ``auth.refresh_tokens``."""
    # 400 characters: a User-Agent is attacker-chosen input, and this column is
    # not a place to store an essay. 45 is the widest an IPv6 literal gets.
    op.add_column(
        "refresh_tokens",
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        schema="auth",
    )


def downgrade() -> None:
    """Drop them again."""
    op.drop_column("refresh_tokens", "ip_address", schema="auth")
    op.drop_column("refresh_tokens", "user_agent", schema="auth")
