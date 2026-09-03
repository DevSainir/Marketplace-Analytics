"""Carry the candidate password on the confirmation code that will apply it.

Revision ID: c7a2f1b45de8
Revises: b4d1e07a9c62
Create Date: 2026-09-03

Closes an account-takeover hole in the signup flow.

Registration created the account with the password from the FIRST attempt and
never replaced it, so proving control of the mailbox and choosing the password
were two separate acts by two possibly different people:

1. an attacker registers `victim@example.com` with a password of their own;
2. the victim gets a "confirmation code" mail, assumes it is their own signup
   (or signs up themselves, is told the address already exists, and asks for a
   code), and enters it;
3. the address is now confirmed on an account whose password the attacker set.

Overwriting on every attempt does not fix it — it only moves the window, since
an attacker registering *after* the victim would then own the password the
victim confirms. The property that actually matters is that the password and
the proof of the mailbox come from the SAME act, so the column added here holds
the digest of the password typed in the attempt this particular code was issued
for, and `confirm_email` applies it at redemption.

Nullable, and null is meaningful: a plain resend inherits the previous
candidate rather than clearing it (otherwise asking for a fresh code would drop
the victim's password and leave the attacker's standing), and a password reset
carries its new password in the redeeming request instead.

Existing rows get NULL, which is correct — they are live codes issued under the
old flow, and a null candidate leaves the account's current password alone.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c7a2f1b45de8"
down_revision = "b4d1e07a9c62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable candidate-password column."""
    op.add_column(
        "verification_codes",
        sa.Column("pending_password_hash", sa.String(length=128), nullable=True),
        schema="auth",
    )


def downgrade() -> None:
    """Drop it again.

    Safe in a way most downgrades here are not: the column holds only
    short-lived candidates for codes that have not been redeemed yet, so losing
    it costs those people one more trip through the signup form rather than any
    committed state.
    """
    op.drop_column("verification_codes", "pending_password_hash", schema="auth")
