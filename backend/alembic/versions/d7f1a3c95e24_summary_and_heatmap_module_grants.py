"""«Сводка» and «Тепловая карта» become grants of their own.

Adds ``summary`` and ``heatmap`` to the module list of every membership and
every invitation that could already open the page, and to both columns' server
default.

**Each page goes to exactly who could open it before.** Until now «Сводка»
opened on «Мониторинг» AND P&L, and «Тепловая карта» on «Мониторинг» — so
``summary`` is written where both were held and ``heatmap`` where «Мониторинг»
was. A manager whose owner closed P&L to them does not find the кабинет's
revenue on «Сводка» the morning after. Unlike ``b5d3e8a61f90``, which could
grant «Реклама» to everyone because every holder of «Мониторинг» had read it.

**One widening, decided by the product owner on 2026-10-12.** A grant now
opens its whole page, so the heatmap's money metrics (выручка, прибыль, маржа)
no longer also ask for P&L — and a manager holding «Мониторинг» without P&L,
who kept the page, now sees them there. The alternative was taking the page
away from those managers (our own organisation's among them); an owner who
wants the money closed to one of them switches «Тепловая карта» off.

Revision ID: d7f1a3c95e24
Revises: e8b3d5a1c962
Create Date: 2026-10-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "d7f1a3c95e24"
down_revision: str | None = "e8b3d5a1c962"
branch_labels: str | None = None
depends_on: str | None = None

#: Written out rather than imported from the model, as in ``9fc926f7c120``.
_BEFORE = '\'["monitoring", "finreports", "ab_tests", "advertising"]\'::jsonb'
_AFTER = '\'["monitoring", "finreports", "ab_tests", "advertising", "summary", "heatmap"]\'::jsonb'
_TABLES = ("memberships", "invitations")

#: Literal statements, one per table and key, so nothing is assembled from a string.
_GRANT = (
    "UPDATE organizations.memberships SET modules = modules || '[\"summary\"]'::jsonb "
    'WHERE modules @> \'["monitoring", "finreports"]\'::jsonb '
    "AND NOT modules @> '[\"summary\"]'::jsonb",
    "UPDATE organizations.invitations SET modules = modules || '[\"summary\"]'::jsonb "
    'WHERE modules @> \'["monitoring", "finreports"]\'::jsonb '
    "AND NOT modules @> '[\"summary\"]'::jsonb",
    "UPDATE organizations.memberships SET modules = modules || '[\"heatmap\"]'::jsonb "
    "WHERE modules @> '[\"monitoring\"]'::jsonb "
    "AND NOT modules @> '[\"heatmap\"]'::jsonb",
    "UPDATE organizations.invitations SET modules = modules || '[\"heatmap\"]'::jsonb "
    "WHERE modules @> '[\"monitoring\"]'::jsonb "
    "AND NOT modules @> '[\"heatmap\"]'::jsonb",
)
_REVOKE = (
    "UPDATE organizations.memberships SET modules = modules - 'summary' - 'heatmap'",
    "UPDATE organizations.invitations SET modules = modules - 'summary' - 'heatmap'",
)


def upgrade() -> None:
    """Grant each page where it was already reachable, and make both part of the default."""
    for table in _TABLES:
        op.alter_column(table, "modules", server_default=sa.text(_AFTER), schema="organizations")
    for statement in _GRANT:
        op.execute(statement)


def downgrade() -> None:
    """Take both keys back out of every row and the default."""
    for statement in _REVOKE:
        op.execute(statement)
    for table in _TABLES:
        op.alter_column(table, "modules", server_default=sa.text(_BEFORE), schema="organizations")
