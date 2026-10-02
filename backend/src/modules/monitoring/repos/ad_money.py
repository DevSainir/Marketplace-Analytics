"""Advertising money in the кабинет's own currency: the RUB→KGS conversion sweep.

WB states each campaign's money in the currency the campaign was created in —
RUB before it moved the ad accounts to KGS on 2026-08-20, KGS after — while a
Kyrgyz кабинет settles, and is reported, in KGS. Every rouble of ad money is
therefore converted where it is stored, at the Bank of Russia rate of its own
day, the rate WB uses for every RUB→KGS conversion it makes itself
(wildberries-api/references/currencies.md). Storing the converted figure means
every reader — the matrix, the heatmap, the P&L, «Сводка», A/Б — gets one
currency without knowing a conversion happened.

**Which кабинет converts** is read off its own sales funnel: WB answers the
funnel's money in the settlement currency, so an article whose funnel speaks
KGS belongs to a KGS кабинет. A RUB кабинет's article never matches, and its
RUB ads stay as they are.

**The sweep is idempotent and re-runnable.** It converts only rows still as
WB served them (``fx_rate IS NULL``); the harvest writes every row that way,
so a re-harvest of a rouble day is converted again rather than left raw. A day
past the last loaded rate (or more than :data:`MAX_RATE_AGE_DAYS` after one)
stays in roubles, and the screens show «—» for the sums it would mix.

What was converted keeps its mark: ``fx_from = 'RUB'`` and ``fx_rate``, the
factor the WB figure was multiplied by — ``amount / fx_rate`` is WB's number.
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.monitoring.models import CbrRate, SalesFunnelDaily
from src.modules.monitoring.repos.base import workspace_sku_select

#: WB moved every ad account to KGS on this day. A row harvested before WB's
#: label was recorded (``currency = ''``) and dated earlier was billed in RUB.
AD_ACCOUNT_SWITCH = date(2026, 8, 20)

#: The Bank publishes on working days; the longest gap in its calendar is the
#: New Year holidays — 28.12.2024 to 11.01.2025, 14 days. A rate older than this
#: is not the day's.
MAX_RATE_AGE_DAYS = 15

# Each table's rows get the rate of THEIR day, as the latest rate on or before
# it, and only for currencies the rate table holds (KGS today).
_RATE_DAY = """
rate_day AS (
    SELECT DISTINCT ON (d.day, c.currency)
        d.day, c.currency, c.nominal::numeric / c.value AS factor
    FROM (
        SELECT generate_series(
            (SELECT min(rate_date) FROM monitoring.cbr_rate), CURRENT_DATE, interval '1 day'
        )::date AS day
    ) AS d
    JOIN monitoring.cbr_rate AS c
        ON c.rate_date <= d.day AND c.rate_date > d.day - CAST(:max_age AS integer)
    ORDER BY d.day, c.currency, c.rate_date DESC
)"""

# The кабинет's currency per article: what its кабинет's funnel answers in. By
# кабинет, not by article — a card delisted before WB served funnel sums has no
# currency of its own, and its old roubles are the кабинет's like any other's.
_TARGET = """
cabinet AS (
    SELECT c.workspace_id, max(f.currency) AS currency
    FROM monitoring.product_card AS c
    JOIN monitoring.sales_funnel_daily AS f ON f.nm_id = c.nm_id
    WHERE f.currency <> '' AND c.workspace_id IN (
        SELECT pc.workspace_id FROM monitoring.product_card AS pc WHERE pc.nm_id IN (
            SELECT a.nm_id FROM monitoring.advertising_stat_daily AS a WHERE {scope_a}
        )
    )
    GROUP BY c.workspace_id
),
target AS (
    SELECT c.nm_id, k.currency
    FROM monitoring.product_card AS c JOIN cabinet AS k ON k.workspace_id = c.workspace_id
)"""

_STATS = """
WITH {rate_day}, {target}
UPDATE monitoring.advertising_stat_daily AS a
SET spend = round(a.spend * r.factor, 2),
    order_sum = round(a.order_sum * r.factor, 2),
    currency = t.currency,
    fx_from = 'RUB',
    fx_rate = r.factor
FROM target AS t, rate_day AS r
WHERE t.nm_id = a.nm_id AND r.currency = t.currency AND r.day = a.stat_date
  AND t.currency <> 'RUB' AND a.fx_rate IS NULL
  AND (a.currency = 'RUB' OR (a.currency = '' AND a.stat_date < :switch))
  AND {scope_a}
"""

# The search-zone and cluster slices carry no currency of their own: they are
# the campaign's, and a campaign's currency is fixed for life, so a campaign
# any of whose fullstats rows was in roubles is a rouble campaign.
_SLICES = """
WITH {rate_day}, {target},
rub_campaign AS (
    SELECT DISTINCT a.campaign_id FROM monitoring.advertising_stat_daily AS a
    WHERE (a.fx_from = 'RUB' OR a.currency = 'RUB') AND {scope_a}
)
UPDATE monitoring.{table} AS s
SET spend = round(s.spend * r.factor, 2), fx_from = 'RUB', fx_rate = r.factor
FROM rub_campaign AS rc, target AS t, rate_day AS r
WHERE s.campaign_id = rc.campaign_id AND t.nm_id = s.nm_id
  AND r.currency = t.currency AND r.day = s.stat_date
  AND t.currency <> 'RUB' AND s.fx_rate IS NULL
"""

# The ledger keys on currency, so a converted row moves to the кабинет's
# currency and merges with a same-day row WB already stated in it (20.08 split
# one document across both).
_LEDGER = """
WITH {rate_day}, {target},
campaign_target AS (
    SELECT a.campaign_id, max(t.currency) AS currency
    FROM monitoring.advertising_stat_daily AS a JOIN target AS t ON t.nm_id = a.nm_id
    WHERE {scope_a}
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
"""


#: The conversion mark, reset on every write: a harvested row is WB's figure.
FX_COLUMNS: tuple[str, str] = ("fx_from", "fx_rate")


def as_served(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Mark rows about to be written as WB served them, for the sweep to convert.

    Every upsert of ad money goes through this, so a re-harvest of a rouble day
    that was converted before cannot leave WB's roubles under the old mark.
    """
    return [{**row, "fx_from": "", "fx_rate": None} for row in rows]


def _statements(scoped: bool) -> list[str]:
    """The four sweeps, in order: fullstats first — the slices read its marks."""
    scope_a = "a.campaign_id = ANY(:ids)" if scoped else "TRUE"
    parts = {"rate_day": _RATE_DAY, "target": _TARGET.format(scope_a=scope_a)}
    return [
        _STATS.format(**parts, scope_a=scope_a),
        _SLICES.format(**parts, scope_a=scope_a, table="advertising_search_stat_daily"),
        _SLICES.format(**parts, scope_a=scope_a, table="advertising_cluster_stat_daily"),
        _LEDGER.format(**parts, scope_a=scope_a),
    ]


async def convert_rouble_ad_money(
    session: AsyncSession, *, campaign_ids: Iterable[int] | None = None
) -> int:
    """Convert every rouble ad row still as WB served it into the кабинет's currency.

    Args:
        session: An open session; the caller owns the transaction.
        campaign_ids: Restrict the sweep to these campaigns — what a harvest just
            wrote. ``None`` sweeps everything (the one-off after loading rates).

    Returns:
        How many rows were converted, over the four tables.
    """
    ids = None if campaign_ids is None else sorted(set(campaign_ids))
    if ids is not None and not ids:
        return 0
    scope: dict[str, object] = {"max_age": MAX_RATE_AGE_DAYS}
    if ids is not None:
        scope["ids"] = ids
    converted = 0
    for index, statement in enumerate(_statements(scoped=ids is not None)):
        # Only the fullstats sweep reads the switch date.
        params = {**scope, "switch": AD_ACCOUNT_SWITCH} if index == 0 else scope
        result = await session.execute(text(statement), params)
        converted += int(getattr(result, "rowcount", 0) or 0)
    return converted


@dataclass(frozen=True)
class RateBook:
    """RUB→``currency`` factors by day, for figures converted in Python.

    The same rule as the SQL sweep: a day takes the latest Bank rate on or
    before it, and none older than :data:`MAX_RATE_AGE_DAYS`. A rouble кабинет
    — or one whose currency is not known yet — converts nothing: its factor is 1.
    """

    currency: str
    dates: tuple[date, ...] = ()
    factors: tuple[Decimal, ...] = ()

    def factor(self, day: date) -> Decimal | None:
        """Units of :attr:`currency` per rouble on ``day``; ``None`` without a rate."""
        if self.currency in ("", "RUB"):
            return Decimal(1)
        index = bisect_right(self.dates, day) - 1
        if index < 0 or (day - self.dates[index]).days >= MAX_RATE_AGE_DAYS:
            return None
        return self.factors[index]


async def load_rate_book(session: AsyncSession, *, currency: str) -> RateBook:
    """Every loaded Bank rate of ``currency``, oldest first; empty for RUB or ``""``."""
    if not currency or currency == "RUB":
        return RateBook(currency=currency)
    rows = (
        await session.execute(
            select(CbrRate.rate_date, CbrRate.nominal, CbrRate.value)
            .where(CbrRate.currency == currency)
            .order_by(CbrRate.rate_date)
        )
    ).all()
    return RateBook(
        currency=currency,
        dates=tuple(day for day, _, _ in rows),
        factors=tuple(Decimal(nominal) / Decimal(value) for _, nominal, value in rows),
    )


async def cabinet_currency(session: AsyncSession, *, workspace_id: uuid.UUID) -> str:
    """The currency a кабинет settles in, as its own funnel states it; ``""`` unknown.

    WB answers the funnel's money in the settlement currency, so monitoring
    knows its кабинет's currency without asking the P&L.
    """
    stmt = (
        select(SalesFunnelDaily.currency)
        .where(
            SalesFunnelDaily.nm_id.in_(workspace_sku_select(workspace_id)),
            SalesFunnelDaily.currency != "",
        )
        .order_by(SalesFunnelDaily.stat_date.desc())
        .limit(1)
    )
    return str((await session.execute(stmt)).scalar_one_or_none() or "")
