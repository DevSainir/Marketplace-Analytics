"""Stamp accounts that predate the login confirmation gate as confirmed.

Revision ID: b4d1e07a9c62
Revises: 9fc926f7c120
Create Date: 2026-09-03

**This migration reverses a decision `e7c3a91d8b45` made on purpose, and the
reversal is the point.** That migration left every existing account with
``email_confirmed_at IS NULL``, reasoning that stamping them would "write a fact
nobody checked" — which was right while confirmation gated nothing those
accounts needed. It gated activation and invitation acceptance only, so an
unconfirmed veteran account kept working untouched.

That reasoning expires the moment `/login` starts refusing unconfirmed
addresses. Registration now creates the account and issues NO session until the
mailed code comes back, and login sends an unconfirmed address to the
confirmation screen instead of signing it in. Applied to the accounts already in
the table, that logs out **every existing user at once** — production held 5
accounts when this was written and all 5 were unconfirmed, the owner among them.

So the choice is not "assert an unverified fact" against "assert nothing". It is
that against "lock every existing customer out of a product they are paying
for", and locking them out is the worse error by a wide margin. These accounts
proved themselves the way accounts did before the gate existed: they were
created, used, and in several cases redeemed an activation code we handed over
by hand.

Only rows that exist WHEN THIS RUNS are stamped. Anything registered afterwards
goes through the new flow and gets its timestamp by confirming, so this is a
one-time amnesty and not a permanent exemption.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b4d1e07a9c62"
down_revision = "9fc926f7c120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Stamp every currently-unconfirmed account as confirmed."""
    # `now()`, not the account's own `created_at`: the timestamp records when we
    # decided to trust the address, which is now, and dating it earlier would
    # fabricate a confirmation event that never happened.
    op.execute(
        sa.text("UPDATE auth.users SET email_confirmed_at = now() WHERE email_confirmed_at IS NULL")
    )


def downgrade() -> None:
    """Deliberately does nothing.

    The rows this touched are indistinguishable from accounts that confirmed
    normally in the same window, so a downgrade cannot tell them apart. Clearing
    every recent confirmation to undo an amnesty would lock out real users to
    reverse a change that was made to avoid locking out real users.
    """
