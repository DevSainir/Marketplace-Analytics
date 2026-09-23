"""Bookkeeping for the provisional daily settlement tail.

WB forms a realization report per DAY as well as per week — ``period: "daily"``
on the same two Finance methods, defaulting to ``weekly``, which is why this
service read only the weekly half until 2026-09-23. A day's report is served the
following morning, so the tail is what lets the P&L reach yesterday instead of
last Sunday.

The rows themselves need no new table: measured on «Демо» over the closed
week 14.09-20.09, the seven daily reports and weekly report 989438999 are the
same 4 424 rows sharing their ``rrdId`` one for one, so they go into
``logistics_transaction`` like any others.

This table is for the two things that are new. **Which daily reports are held**,
so the lane does not re-fetch them at one request a minute — kept apart from
``financial_report`` on purpose, because that table is where the weekly
machinery reads «how far is this workspace settled» from as ``max(date_to)``, and
a daily header for yesterday would answer it with yesterday and stop the weekly
report ever being asked for again. And **what each report's rows looked like when
first ingested**, because whether WB revises a daily report after serving it is
not yet known, and the day-later re-read that answers it needs something to
compare against.

Revision ID: f3c8a71b06d2
Revises: a1c7e93b65f2
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f3c8a71b06d2"
down_revision: str | None = "a1c7e93b65f2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create ``finreports.daily_settlement_report``."""
    op.create_table(
        "daily_settlement_report",
        # BigInteger: a daily id is fifteen digits — `{supplier}{YYYYMMDD}`.
        sa.Column("report_id", sa.BigInteger(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("create_dt", sa.Date(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("digest", sa.String(32), nullable=False, server_default=""),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_rows", sa.Integer(), nullable=True),
        sa.Column("verified_digest", sa.String(32), nullable=True),
        sa.Column("verdict", sa.String(16), nullable=True),
        schema="finreports",
    )
    op.create_index(
        op.f("ix_finreports_daily_settlement_report_workspace_id"),
        "daily_settlement_report",
        ["workspace_id"],
        schema="finreports",
    )
    op.create_index(
        op.f("ix_finreports_daily_settlement_report_day"),
        "daily_settlement_report",
        ["day"],
        schema="finreports",
    )
    # The verification queue's own access path: «this workspace's unverified
    # reports, oldest first». Partial, because a verified report never leaves the
    # table and within a month they outnumber the pending ones many times over.
    op.create_index(
        "ix_daily_settlement_pending",
        "daily_settlement_report",
        ["workspace_id", "first_seen_at"],
        schema="finreports",
        postgresql_where=sa.text("verdict IS NULL"),
    )
    # Attached per TABLE, so a new one is born unguarded — and the failure
    # direction is open. `tests/integration/core/test_migrations.py` is what
    # notices when this loop is forgotten.
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON finreports.daily_settlement_report "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )


def downgrade() -> None:
    """Drop the table. The rows it books stay — they are real settlement rows."""
    op.drop_table("daily_settlement_report", schema="finreports")
