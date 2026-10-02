"""Monitoring: Bank of Russia rates, and rouble ad money converted to the кабинет's currency.

WB moved every ad account from RUB to KGS on 2026-08-20. A Kyrgyz кабинет's
advertising before that day — and the tail of campaigns created before it,
which kept billing in roubles until 2026-09-22 — is stored by WB in RUB, while
everything it is compared with (the funnel's order sums, the settlement) is in
KGS. This converts it where it is stored, at the rate WB itself converts at:
the Bank of Russia's, of the row's own day (checked to five decimals against
WB's conversions on 11.07, 08.08, 19.08, 03.09 and 12.09.2026 — see
wildberries-api/references/currencies.md).

* monitoring.cbr_rate — the KGS rates 2023-01-10 .. 2026-10-02, loaded once
  from alembic/data/cbr_kgs_rates.csv (XML_dynamic.asp, R01370).
  No rates task: there is no new rouble spend to convert.
* fx_from/fx_rate on the four ad money tables — what WB stated the
  row in, and the factor it was multiplied by; NULL for a row as WB served it.
* the one-off sweep over the whole history. It is the SQL of
  repos/ad_money.py as of this revision, frozen here on purpose: the
  harvest runs the module's copy on what it writes from now on.

A кабинет is converted only if its funnel answers in KGS (read per кабинет, so
a card delisted before WB valued the funnel is converted with the rest); a
rouble кабинет's rouble ads stay as they are. The downgrade drops the marks and the table but
cannot restore WB's roubles — amount / fx_rate recovers them to the kopeck.

Revision ID: c4e8a2f71d39
Revises: a9d4f2c7e815
Create Date: 2026-10-02
"""

from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8a2f71d39"
down_revision: str | None = "a9d4f2c7e815"
branch_labels: str | None = None
depends_on: str | None = None

_RATES = Path(__file__).resolve().parent.parent / "data" / "cbr_kgs_rates.csv"
_TABLES = (
    "advertising_stat_daily",
    "advertising_search_stat_daily",
    "advertising_cluster_stat_daily",
    "advertising_write_off_daily",
)

# fullstats, then its search and cluster slices, then the write-off ledger.
_SWEEP = (
    """
WITH
rate_day AS (
    SELECT DISTINCT ON (d.day, c.currency)
        d.day, c.currency, c.nominal::numeric / c.value AS factor
    FROM (
        SELECT generate_series(
            (SELECT min(rate_date) FROM monitoring.cbr_rate), CURRENT_DATE, interval '1 day'
        )::date AS day
    ) AS d
    JOIN monitoring.cbr_rate AS c
        ON c.rate_date <= d.day AND c.rate_date > d.day - 15
    ORDER BY d.day, c.currency, c.rate_date DESC
),
cabinet AS (
    SELECT c.workspace_id, max(f.currency) AS currency
    FROM monitoring.product_card AS c
    JOIN monitoring.sales_funnel_daily AS f ON f.nm_id = c.nm_id
    WHERE f.currency <> '' AND c.workspace_id IN (
        SELECT pc.workspace_id FROM monitoring.product_card AS pc WHERE pc.nm_id IN (
            SELECT a.nm_id FROM monitoring.advertising_stat_daily AS a WHERE TRUE
        )
    )
    GROUP BY c.workspace_id
),
target AS (
    SELECT c.nm_id, k.currency
    FROM monitoring.product_card AS c JOIN cabinet AS k ON k.workspace_id = c.workspace_id
)
UPDATE monitoring.advertising_stat_daily AS a
SET spend = round(a.spend * r.factor, 2),
    order_sum = round(a.order_sum * r.factor, 2),
    currency = t.currency,
    fx_from = 'RUB',
    fx_rate = r.factor
FROM target AS t, rate_day AS r
WHERE t.nm_id = a.nm_id AND r.currency = t.currency AND r.day = a.stat_date
  AND t.currency <> 'RUB' AND a.fx_rate IS NULL
  AND (a.currency = 'RUB' OR (a.currency = '' AND a.stat_date < DATE '2026-08-20'))
  AND TRUE
""",
    """
WITH
rate_day AS (
    SELECT DISTINCT ON (d.day, c.currency)
        d.day, c.currency, c.nominal::numeric / c.value AS factor
    FROM (
        SELECT generate_series(
            (SELECT min(rate_date) FROM monitoring.cbr_rate), CURRENT_DATE, interval '1 day'
        )::date AS day
    ) AS d
    JOIN monitoring.cbr_rate AS c
        ON c.rate_date <= d.day AND c.rate_date > d.day - 15
    ORDER BY d.day, c.currency, c.rate_date DESC
),
cabinet AS (
    SELECT c.workspace_id, max(f.currency) AS currency
    FROM monitoring.product_card AS c
    JOIN monitoring.sales_funnel_daily AS f ON f.nm_id = c.nm_id
    WHERE f.currency <> '' AND c.workspace_id IN (
        SELECT pc.workspace_id FROM monitoring.product_card AS pc WHERE pc.nm_id IN (
            SELECT a.nm_id FROM monitoring.advertising_stat_daily AS a WHERE TRUE
        )
    )
    GROUP BY c.workspace_id
),
target AS (
    SELECT c.nm_id, k.currency
    FROM monitoring.product_card AS c JOIN cabinet AS k ON k.workspace_id = c.workspace_id
),
rub_campaign AS (
    SELECT DISTINCT a.campaign_id FROM monitoring.advertising_stat_daily AS a
    WHERE (a.fx_from = 'RUB' OR a.currency = 'RUB') AND TRUE
)
UPDATE monitoring.advertising_search_stat_daily AS s
SET spend = round(s.spend * r.factor, 2), fx_from = 'RUB', fx_rate = r.factor
FROM rub_campaign AS rc, target AS t, rate_day AS r
WHERE s.campaign_id = rc.campaign_id AND t.nm_id = s.nm_id
  AND r.currency = t.currency AND r.day = s.stat_date
  AND t.currency <> 'RUB' AND s.fx_rate IS NULL
""",
    """
WITH
rate_day AS (
    SELECT DISTINCT ON (d.day, c.currency)
        d.day, c.currency, c.nominal::numeric / c.value AS factor
    FROM (
        SELECT generate_series(
            (SELECT min(rate_date) FROM monitoring.cbr_rate), CURRENT_DATE, interval '1 day'
        )::date AS day
    ) AS d
    JOIN monitoring.cbr_rate AS c
        ON c.rate_date <= d.day AND c.rate_date > d.day - 15
    ORDER BY d.day, c.currency, c.rate_date DESC
),
cabinet AS (
    SELECT c.workspace_id, max(f.currency) AS currency
    FROM monitoring.product_card AS c
    JOIN monitoring.sales_funnel_daily AS f ON f.nm_id = c.nm_id
    WHERE f.currency <> '' AND c.workspace_id IN (
        SELECT pc.workspace_id FROM monitoring.product_card AS pc WHERE pc.nm_id IN (
            SELECT a.nm_id FROM monitoring.advertising_stat_daily AS a WHERE TRUE
        )
    )
    GROUP BY c.workspace_id
),
target AS (
    SELECT c.nm_id, k.currency
    FROM monitoring.product_card AS c JOIN cabinet AS k ON k.workspace_id = c.workspace_id
),
rub_campaign AS (
    SELECT DISTINCT a.campaign_id FROM monitoring.advertising_stat_daily AS a
    WHERE (a.fx_from = 'RUB' OR a.currency = 'RUB') AND TRUE
)
UPDATE monitoring.advertising_cluster_stat_daily AS s
SET spend = round(s.spend * r.factor, 2), fx_from = 'RUB', fx_rate = r.factor
FROM rub_campaign AS rc, target AS t, rate_day AS r
WHERE s.campaign_id = rc.campaign_id AND t.nm_id = s.nm_id
  AND r.currency = t.currency AND r.day = s.stat_date
  AND t.currency <> 'RUB' AND s.fx_rate IS NULL
""",
    """
WITH
rate_day AS (
    SELECT DISTINCT ON (d.day, c.currency)
        d.day, c.currency, c.nominal::numeric / c.value AS factor
    FROM (
        SELECT generate_series(
            (SELECT min(rate_date) FROM monitoring.cbr_rate), CURRENT_DATE, interval '1 day'
        )::date AS day
    ) AS d
    JOIN monitoring.cbr_rate AS c
        ON c.rate_date <= d.day AND c.rate_date > d.day - 15
    ORDER BY d.day, c.currency, c.rate_date DESC
),
cabinet AS (
    SELECT c.workspace_id, max(f.currency) AS currency
    FROM monitoring.product_card AS c
    JOIN monitoring.sales_funnel_daily AS f ON f.nm_id = c.nm_id
    WHERE f.currency <> '' AND c.workspace_id IN (
        SELECT pc.workspace_id FROM monitoring.product_card AS pc WHERE pc.nm_id IN (
            SELECT a.nm_id FROM monitoring.advertising_stat_daily AS a WHERE TRUE
        )
    )
    GROUP BY c.workspace_id
),
target AS (
    SELECT c.nm_id, k.currency
    FROM monitoring.product_card AS c JOIN cabinet AS k ON k.workspace_id = c.workspace_id
),
campaign_target AS (
    SELECT a.campaign_id, max(t.currency) AS currency
    FROM monitoring.advertising_stat_daily AS a JOIN target AS t ON t.nm_id = a.nm_id
    WHERE TRUE
    GROUP BY a.campaign_id
),
moved AS (
    DELETE FROM monitoring.advertising_write_off_daily AS w
    USING campaign_target AS ct, rate_day AS r
    WHERE w.currency = 'RUB' AND ct.campaign_id = w.campaign_id AND ct.currency <> 'RUB'
      AND r.currency = ct.currency AND r.day = w.stat_date
    RETURNING w.stat_date, w.campaign_id, w.payment_type, ct.currency AS currency,
              round(w.amount * r.factor, 2) AS amount, w.write_offs, r.factor
)
INSERT INTO monitoring.advertising_write_off_daily
    (stat_date, campaign_id, payment_type, currency, amount, write_offs, fx_from, fx_rate)
SELECT stat_date, campaign_id, payment_type, currency, amount, write_offs, 'RUB', factor
FROM moved
ON CONFLICT (stat_date, campaign_id, payment_type, currency) DO UPDATE
SET amount = monitoring.advertising_write_off_daily.amount + EXCLUDED.amount,
    write_offs = monitoring.advertising_write_off_daily.write_offs + EXCLUDED.write_offs,
    fx_from = 'RUB',
    fx_rate = EXCLUDED.fx_rate
""",
)


def upgrade() -> None:
    """Load the rates, mark the ad tables, convert the rouble history."""
    rates = op.create_table(
        "cbr_rate",
        sa.Column("currency", sa.String(8), primary_key=True),
        sa.Column("rate_date", sa.Date(), primary_key=True),
        sa.Column("nominal", sa.Integer(), nullable=False),
        sa.Column("value", sa.Numeric(12, 4), nullable=False),
        schema="monitoring",
    )
    # Every data table in a guarded schema refuses a stray TRUNCATE; a new one
    # is born unprotected unless attached here (test_migrations.py notices).
    op.execute(
        "CREATE TRIGGER guard_against_truncate "
        "BEFORE TRUNCATE ON monitoring.cbr_rate "
        "FOR EACH STATEMENT EXECUTE FUNCTION organizations.guard_against_truncate()"
    )
    with _RATES.open(encoding="utf-8") as handle:
        op.bulk_insert(
            rates,
            [
                {
                    "currency": "KGS",
                    "rate_date": date.fromisoformat(row["rate_date"]),
                    "nominal": int(row["nominal"]),
                    "value": Decimal(row["value"]),
                }
                for row in csv.DictReader(handle)
            ],
        )
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column("fx_from", sa.String(8), server_default="", nullable=False),
            schema="monitoring",
        )
        op.add_column(
            table, sa.Column("fx_rate", sa.Numeric(12, 8), nullable=True), schema="monitoring"
        )
    for statement in _SWEEP:
        op.execute(statement)


def downgrade() -> None:
    """Drop the marks and the rates; the converted figures stay converted."""
    for table in _TABLES:
        op.drop_column(table, "fx_rate", schema="monitoring")
        op.drop_column(table, "fx_from", schema="monitoring")
    op.drop_table("cbr_rate", schema="monitoring")
