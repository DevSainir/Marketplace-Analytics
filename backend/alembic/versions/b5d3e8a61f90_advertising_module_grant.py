"""The «Реклама» grant, on for everyone.

Adds ``advertising`` to the module list of every membership and every
invitation, and to both columns' server default.

**Granted, not withheld, on the deploy that introduces it** — the same risk
decision as ``9fc926f7c120``. Every member of our own organisation holding
«Мониторинг» read the page before; none of them may find it gone, and a
customer's owner who wants it closed for a manager does that deliberately
afterwards rather than by default.

Revision ID: b5d3e8a61f90
Revises: c3a9e5d17f42
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "b5d3e8a61f90"
down_revision: str | None = "c3a9e5d17f42"
branch_labels: str | None = None
depends_on: str | None = None

#: Written out rather than imported from the model, as in ``9fc926f7c120``.
_BEFORE = '\'["monitoring", "finreports", "ab_tests"]\'::jsonb'
_AFTER = '\'["monitoring", "finreports", "ab_tests", "advertising"]\'::jsonb'
_TABLES = ("memberships", "invitations")

#: Literal statements, one per table, so nothing is assembled from a string.
_GRANT = (
    "UPDATE organizations.memberships SET modules = modules || '[\"advertising\"]'::jsonb "
    "WHERE NOT modules @> '[\"advertising\"]'::jsonb",
    "UPDATE organizations.invitations SET modules = modules || '[\"advertising\"]'::jsonb "
    "WHERE NOT modules @> '[\"advertising\"]'::jsonb",
)
_REVOKE = (
    "UPDATE organizations.memberships SET modules = modules - 'advertising'",
    "UPDATE organizations.invitations SET modules = modules - 'advertising'",
)


def upgrade() -> None:
    """Grant «Реклама» to every row and make it part of the default."""
    for table in _TABLES:
        op.alter_column(table, "modules", server_default=sa.text(_AFTER), schema="organizations")
    for statement in _GRANT:
        op.execute(statement)


def downgrade() -> None:
    """Take the grant back out of every row and the default."""
    for statement in _REVOKE:
        op.execute(statement)
    for table in _TABLES:
        op.alter_column(table, "modules", server_default=sa.text(_BEFORE), schema="organizations")
