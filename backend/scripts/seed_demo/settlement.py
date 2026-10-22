"""The demo's settlement: which weekly reports exist, their headers, the cost prices.

The P&L is derived from nothing else (``docs/finreports/PNL.md``): a header per
report says which periods exist, and the detail rows carry every figure. The
rows are built in :mod:`scripts.seed_demo.settlement_rows`; this module walks
the periods, states each report's total, and writes it all.

Periods are WB's: Monday to Sunday, cut at a month end. The newest one is the
last period that has fully ended, which is exactly what a seller holds on a
Wednesday — so the page shows no «report formed, waiting for the API» note.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import CURRENCY, REPORT_ID_BASE, SKUS
from scripts.seed_demo.settlement_rows import DetailRows, account_charges, article_day
from scripts.seed_demo.writes import insert_rows
from src.modules.finreports.constants import REFUND_DOC_TYPE
from src.modules.finreports.models import FinancialReport, LogisticsTransaction, ProductCostPrice
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.finreports.services.settlement_calendar import (
    settlement_period_end,
    settlement_period_start,
)

#: How many weekly reports the demo holds.
REPORTS = 9


@dataclass(frozen=True)
class Period:
    """One weekly report's period and id."""

    report_id: int
    date_from: date
    date_to: date

    def days(self) -> list[date]:
        """Every day of the period, oldest first."""
        return sim.window(self.date_to, (self.date_to - self.date_from).days + 1)


def periods(today: date) -> list[Period]:
    """The demo's reports, newest first: the last fully ended periods before ``today``."""
    result: list[Period] = []
    date_to = settlement_period_start(today) - timedelta(days=1)
    while len(result) < REPORTS:
        date_from = settlement_period_start(date_to)
        assert settlement_period_end(date_from) == date_to
        report_id = REPORT_ID_BASE + date_to.toordinal() % 100_000
        result.append(Period(report_id, date_from, date_to))
        date_to = date_from - timedelta(days=1)
    return result


def settlement_rows(
    workspace_id: uuid.UUID, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every report header and every detail row of the demo's settlement.

    Returns:
        ``(headers, detail rows)``. Each header carries WB's own payout total,
        computed from its rows the way WB states it, so the ledger's check of
        every booked report against WB's figure agrees.
    """
    rows = DetailRows(workspace_id)
    headers: list[dict[str, Any]] = []
    for index, period in enumerate(periods(today)):
        first = len(rows.rows)
        for day in period.days():
            for sku in SKUS:
                article_day(rows, period.report_id, sku, sim.sale_day(sku, day, today))
        # A fine every other week, on a different article each time.
        fined = SKUS[index % len(SKUS)] if index % 2 == 0 else None
        account_charges(rows, period.report_id, period.days(), today, fined)
        for_pay = sum(
            (
                -row["ppvz_for_pay"]
                if row["doc_type_name"] == REFUND_DOC_TYPE
                else row["ppvz_for_pay"]
                for row in rows.rows[first:]
            ),
            Decimal("0.00"),
        )
        headers.append(
            {
                "report_id": period.report_id,
                "workspace_id": workspace_id,
                "date_from": period.date_from,
                "date_to": period.date_to,
                "currency": CURRENCY,
                "create_dt": period.date_to + timedelta(days=1),
                "wb_for_pay_sum": for_pay,
            }
        )
    return headers, rows.rows


def cost_rows(workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    """One cost price per article, in the settlement's currency."""
    return [
        {
            "workspace_id": workspace_id,
            "nm_id": sku.nm_id,
            "cost": sku.cost,
            "currency": CURRENCY,
            "vendor_code": sku.vendor_code,
            "source": "seed",
            "note": "",
        }
        for sku in SKUS
    ]


async def seed_settlement(session: AsyncSession, workspace_id: uuid.UUID, today: date) -> int:
    """Write the reports, their detail, the cost prices, and warm the P&L rollup."""
    headers, detail = settlement_rows(workspace_id, today)
    written = await insert_rows(session, FinancialReport, headers)
    written += await insert_rows(session, LogisticsTransaction, detail)
    written += await insert_rows(session, ProductCostPrice, cost_rows(workspace_id))
    # The rollup would build itself on the first page load; building it here
    # keeps that first load as fast as every later one.
    span = periods(today)
    await SettlementRollup(session).ensure_fresh(
        workspace_id=workspace_id, date_from=span[-1].date_from, date_to=span[0].date_to
    )
    return written
