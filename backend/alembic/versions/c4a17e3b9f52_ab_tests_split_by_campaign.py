"""ab_tests: one копилка per advertising campaign, not per card

Revision ID: c4a17e3b9f52
Revises: b8d24f61ca07
Create Date: 2026-09-16

A card is often pushed by two campaigns at once, and until now the poller added
their counters together before storing them: one row per photo per interval,
holding a mixture no later question could take apart. That is not a
presentation detail — the mixture moves on its own. A campaign switched on
halfway through a test lifts every photo that follows it, and the lift reads
exactly like one photo winning.

So the difference between two readings is now taken once per campaign, and
every stored row names the campaign it came from:

* ``ab_test_ad_snapshot`` — the poller's baseline gains ``campaign_id`` in its
  primary key, so each campaign is differenced against its own previous
  reading.
* ``ab_test_variant_stat_window`` — gains ``campaign_id``, and its uniqueness
  (which is what makes a retried pass idempotent) becomes
  ``(variant_id, window_start, campaign_id)``: one interval now writes one row
  per campaign that served it.
* ``ab_test_campaign`` — new: what each campaign is called and what sort it is,
  copied off WB's listing on every pass. Needed because a campaign archived
  mid-test vanishes from that listing while its measurements stay on the page.

**Existing rows keep ``campaign_id = 0``**, and that is honest rather than
convenient: they are the sum of whatever was running at the time, and the parts
were added together before they were stored. They cannot be recovered. The page
shows them as one unnamed campaign, so a test that was running at deploy time
reads as «одна РК» until the next poll splits the new traffic properly.

The baselines are NOT cleared. A snapshot keyed ``(test, 0, day)`` is a reading
of every campaign at once, and the next pass reads them separately: with the old
row still there, campaign 97455930 would be differenced against nothing and
credit its whole day to the photo standing at that moment. So the snapshots are
dropped — the same state a paused test resumes from: seed, credit nothing, carry
on from there.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a17e3b9f52"
down_revision: str | None = "b8d24f61ca07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "ab_tests"


def upgrade() -> None:
    """Add the campaign dimension to the poller's two tables, and the register."""
    op.add_column(
        "ab_test_variant_stat_window",
        sa.Column("campaign_id", sa.BigInteger(), server_default="0", nullable=False),
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "uq_ab_test_variant_stat_window_variant_start",
        "ab_test_variant_stat_window",
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_ab_test_variant_stat_window_variant_start",
        "ab_test_variant_stat_window",
        ["variant_id", "window_start", "campaign_id"],
        schema=_SCHEMA,
    )

    # The baseline cannot survive the change of grain — see the module
    # docstring. Emptied rather than migrated; the next pass seeds a fresh one.
    op.execute("DELETE FROM ab_tests.ab_test_ad_snapshot")
    op.add_column(
        "ab_test_ad_snapshot",
        sa.Column("campaign_id", sa.BigInteger(), server_default="0", nullable=False),
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "pk_ab_test_ad_snapshot", "ab_test_ad_snapshot", schema=_SCHEMA, type_="primary"
    )
    op.create_primary_key(
        "pk_ab_test_ad_snapshot",
        "ab_test_ad_snapshot",
        ["test_id", "campaign_id", "stat_date"],
        schema=_SCHEMA,
    )

    op.create_table(
        "ab_test_campaign",
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=512), server_default="", nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="unknown", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"],
            [f"{_SCHEMA}.ab_test.id"],
            name=op.f("fk_ab_test_campaign_test_id_ab_test"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("test_id", "campaign_id", name=op.f("pk_ab_test_campaign")),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Fold the campaigns back together.

    The windows are summed per ``(variant, window_start)`` rather than dropped:
    the old shape held exactly that sum, so the totals a page shows survive the
    downgrade even though the split does not.
    """
    op.drop_table("ab_test_campaign", schema=_SCHEMA)

    op.execute("DELETE FROM ab_tests.ab_test_ad_snapshot")
    op.drop_constraint(
        "pk_ab_test_ad_snapshot", "ab_test_ad_snapshot", schema=_SCHEMA, type_="primary"
    )
    op.create_primary_key(
        "pk_ab_test_ad_snapshot",
        "ab_test_ad_snapshot",
        ["test_id", "stat_date"],
        schema=_SCHEMA,
    )
    op.drop_column("ab_test_ad_snapshot", "campaign_id", schema=_SCHEMA)

    op.execute(
        """
        WITH folded AS (
            SELECT variant_id,
                   window_start,
                   min(id) AS keep_id,
                   sum(views) AS views,
                   sum(clicks) AS clicks,
                   sum(atbs) AS atbs,
                   sum(orders) AS orders,
                   sum(spend) AS spend
              FROM ab_tests.ab_test_variant_stat_window
             GROUP BY variant_id, window_start
        )
        UPDATE ab_tests.ab_test_variant_stat_window AS w
           SET views = folded.views,
               clicks = folded.clicks,
               atbs = folded.atbs,
               orders = folded.orders,
               spend = folded.spend
          FROM folded
         WHERE w.id = folded.keep_id
        """
    )
    op.execute(
        """
        DELETE FROM ab_tests.ab_test_variant_stat_window AS w
         USING (
            SELECT variant_id, window_start, min(id) AS keep_id
              FROM ab_tests.ab_test_variant_stat_window
             GROUP BY variant_id, window_start
         ) AS folded
         WHERE w.variant_id = folded.variant_id
           AND w.window_start = folded.window_start
           AND w.id <> folded.keep_id
        """
    )
    op.drop_constraint(
        "uq_ab_test_variant_stat_window_variant_start",
        "ab_test_variant_stat_window",
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_ab_test_variant_stat_window_variant_start",
        "ab_test_variant_stat_window",
        ["variant_id", "window_start"],
        schema=_SCHEMA,
    )
    op.drop_column("ab_test_variant_stat_window", "campaign_id", schema=_SCHEMA)
