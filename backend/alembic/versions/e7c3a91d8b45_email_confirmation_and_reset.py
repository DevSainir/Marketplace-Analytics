"""auth: confirmed-address stamp and the codes that prove one

Revision ID: e7c3a91d8b45
Revises: d5b2a8f31c47
Create Date: 2026-09-01

Closes register P1.6 at the schema level: `auth.users.email_confirmed_at` and
`auth.verification_codes`.

**Every existing account is left NULL — unconfirmed — on purpose.** The
tempting alternative is to stamp them all as confirmed on the grounds that they
predate the feature and are known to us. That would write a fact we cannot
support: nobody proved control of those mailboxes, and a column that says
"confirmed" for addresses that were never checked is worse than one that admits
it does not know. It also costs nothing to be honest here, because confirmation
gates only activation and invitation acceptance (and only when
`EMAIL_CONFIRMATION_REQUIRED` is on) — an existing member's account keeps
working untouched.

`email_confirmed_at` is a timestamp rather than a boolean so the *when*
survives. During an incident, "confirmed before we required it" and "confirmed
eleven minutes ago, from an address that also just reset the password" are very
different facts, and a boolean throws that away.

The codes table holds SHA-256 digests, never a redeemable code, and its rows are
measured in minutes. `ON DELETE CASCADE` on the user is right here and is not a
contradiction of the audit log's no-foreign-key rule: this table describes a
*credential*, which has no meaning once the account is gone, whereas the audit
log describes an *event*, which does.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e7c3a91d8b45"
down_revision = "d5b2a8f31c47"
branch_labels = None
depends_on = None

_SCHEMA = "auth"


def upgrade() -> None:
    """Add the confirmation stamp and the verification-code table."""
    op.add_column(
        "users",
        sa.Column("email_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.create_table(
        "verification_codes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(f"{_SCHEMA}.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_verification_codes_user_purpose",
        "verification_codes",
        ["user_id", "purpose"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop the verification codes and the confirmation stamp."""
    op.drop_index(
        "ix_verification_codes_user_purpose", table_name="verification_codes", schema=_SCHEMA
    )
    op.drop_table("verification_codes", schema=_SCHEMA)
    op.drop_column("users", "email_confirmed_at", schema=_SCHEMA)
