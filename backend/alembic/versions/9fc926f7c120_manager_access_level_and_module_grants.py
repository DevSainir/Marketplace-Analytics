"""manager access level and module grants

Adds the two columns that turn "manager" from one thing into a grant the owner
chooses: how much they may do (``access_level``) and which product surfaces
they may reach (``modules``).

**Both server defaults grant everything, and that is the whole migration's
risk decision.** A manager who exists today has full read/write on every
module; backfilling them to anything narrower would revoke access silently, on
a deploy nobody told them about, and the first they would hear of it is a
screen that stopped working. So existing rows widen to exactly what they
already had, and the narrowing is something an owner does deliberately
afterwards.

Autogenerate also proposed dropping ``auth.uq_users_email_lower``. It is a
functional index (``lower(email)``) that alembic cannot reflect and therefore
believes is absent; dropping it would remove the constraint that stops two
accounts differing only in case. Left out on purpose — see
``c9e3a7b1d5f2_perf_indexes_and_email_ci_unique``.

Revision ID: 9fc926f7c120
Revises: e7c3a91d8b45
Create Date: 2026-09-02 17:25:53.731691

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9fc926f7c120"
down_revision: str | None = "e7c3a91d8b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every module there is. Written out rather than imported from the model:
#: a migration describes the schema at one moment in history, and must not
#: change meaning later because an enum grew a member.
_ALL_MODULES = '\'["monitoring", "finreports", "ab_tests"]\'::jsonb'


def upgrade() -> None:
    """Apply the schema changes for this revision."""
    for table in ("invitations", "memberships"):
        op.add_column(
            table,
            sa.Column(
                "access_level",
                sa.String(length=16),
                server_default="read_write",
                nullable=False,
            ),
            schema="organizations",
        )
        op.add_column(
            table,
            sa.Column(
                "modules",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text(_ALL_MODULES),
                nullable=False,
            ),
            schema="organizations",
        )


def downgrade() -> None:
    """Revert the schema changes for this revision."""
    for table in ("memberships", "invitations"):
        op.drop_column(table, "modules", schema="organizations")
        op.drop_column(table, "access_level", schema="organizations")
