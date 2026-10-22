"""The demo's settlement: WB's weekly reports, row by row, and the cost prices.

The P&L is derived from nothing else (``docs/finreports/PNL.md``): a header per
report says which periods exist, and the detail rows — one per sold unit,
returned unit, delivery leg, storage day and deduction — carry every figure.
The rows here follow WB's own shapes, operation labels and sign rules, so the
real derivation runs over them unchanged.

Periods are WB's: Monday to Sunday, cut at a month end. The newest one is the
last period that has fully ended, which is exactly what a seller holds on a
Wednesday — so the page shows no «report formed, waiting for the API» note.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.advertising import cash_spend
from scripts.seed_demo.catalogue import (
    BRAND,
    CURRENCY,
    REPORT_ID_BASE,
    RRD_ID_BASE,
    SKUS,
    WAREHOUSES,
    DemoSku,
    barcode,
    size_weight,
)
from scripts.seed_demo.economics import COMMISSION_PERCENT, sale_amounts
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

#: What WB charges to bring a cancelled or returned unit back.
_RETURN_LEG = Decimal("50.00")
#: Storage, per unit on the warehouses, per day.
_STORAGE_PER_UNIT = Decimal("0.11")
#: Paid acceptance of the period's one supply.
_ACCEPTANCE = Decimal("1350.00")
#: A fine every other week, on the article that earned it.
_PENALTY = Decimal("500.00")
_PENALTY_REASON = "Занижение фактических габаритов упаковки товара"


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


class _Rows:
    """Builds detail rows with the keys and identity every row shares."""

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self._workspace_id = workspace_id
        self._next = RRD_ID_BASE
        self.rows: list[dict[str, Any]] = []

    def add(self, period: Period, day: date, oper: str, **fields: Any) -> dict[str, Any]:
        """Append one row of ``period``, dated ``day``, with ``fields`` set on it."""
        self._next += 1
        row: dict[str, Any] = dict(_ZERO_ROW)
        row.update(
            rrd_id=self._next,
            report_id=period.report_id,
            workspace_id=self._workspace_id,
            rr_dt=day,
            supplier_oper_name=oper,
            currency_name=CURRENCY,
            site_country="Россия",
        )
        row.update(fields)
        self.rows.append(row)
        return row


def _pick(weights: list[float], *key: object) -> int:
    """A deterministic weighted choice: the index ``key`` lands on."""
    point = random.Random(":".join(str(part) for part in key)).random() * sum(weights)  # noqa: S311
    for index, weight in enumerate(weights):
        point -= weight
        if point < 0:
            return index
    return len(weights) - 1


def _units(sku: DemoSku, sale: sim.SaleDay, count: int, kind: str) -> Iterator[dict[str, Any]]:
    """Per-unit identity — size, warehouse, order id — spread the way stock is."""
    sizes = [size_weight(sku, index) for index in range(len(sku.sizes))]
    shares = [share for _, _, share in WAREHOUSES]
    for unit in range(count):
        size = _pick(sizes, "size", kind, sku.nm_id, sale.day, unit)
        warehouse = WAREHOUSES[_pick(shares, "warehouse", kind, sku.nm_id, sale.day, unit)][0]
        yield {
            "nm_id": sku.nm_id,
            "sa_name": sku.vendor_code,
            "ts_name": sku.sizes[size],
            "barcode": barcode(sku, size),
            "subject_name": sku.subject,
            "brand_name": BRAND,
            "office_name": warehouse,
            "srid": f"demo.{kind}.{sku.nm_id}.{sale.day:%Y%m%d}.{unit}",
            "order_dt": sale.order_day,
            "sale_dt": sale.day,
        }


def _sku_day(rows: _Rows, period: Period, sku: DemoSku, sale: sim.SaleDay) -> None:
    """One article's day: its sales and returns, and every delivery leg they cost."""
    money = sale_amounts(sku, sale.order_day)
    unit_money = {
        "quantity": 1,
        "retail_price": money.list_price,
        "retail_amount": money.paid,
        "retail_price_withdisc_rub": money.seller_price,
        "sale_percent": money.sale_percent,
        "commission_percent": COMMISSION_PERCENT,
        "ppvz_spp_prc": money.spp,
        "ppvz_kvw_prc_base": COMMISSION_PERCENT,
        "ppvz_vw": money.commission,
        "ppvz_vw_nds": money.commission_vat,
        "ppvz_sales_commission": sim.money(money.commission),
        "acquiring_fee": money.acquiring,
        "acquiring_percent": Decimal("1.50"),
        "ppvz_for_pay": money.payout,
    }
    for unit in _units(sku, sale, sale.sold, "sale"):
        rows.add(period, sale.day, "Продажа", doc_type_name="Продажа", **unit, **unit_money)
        rows.add(
            period,
            sale.day,
            "Логистика",
            doc_type_name="Продажа",
            bonus_type_name="К клиенту при продаже",
            delivery_amount=1,
            delivery_rub=sku.delivery,
            **unit,
        )
    for unit in _units(sku, sale, sale.returned, "return"):
        rows.add(period, sale.day, "Возврат", doc_type_name=REFUND_DOC_TYPE, **unit, **unit_money)
        rows.add(
            period,
            sale.day,
            "Логистика",
            doc_type_name="Продажа",
            bonus_type_name="От клиента при возврате",
            return_amount=1,
            delivery_rub=_RETURN_LEG,
            **unit,
        )
    for unit in _units(sku, sale, sale.cancelled, "cancel"):
        for reason, leg, cost in (
            ("К клиенту при отмене", "delivery_amount", sku.delivery),
            ("От клиента при отмене", "return_amount", _RETURN_LEG),
        ):
            rows.add(
                period,
                sale.day,
                "Логистика",
                doc_type_name="Продажа",
                bonus_type_name=reason,
                delivery_rub=cost,
                **{leg: 1},
                **unit,
            )


def _account_rows(rows: _Rows, period: Period, today: date, index: int) -> None:
    """The period's charges no article owns: storage, acceptance, advertising, a fine."""
    for day in period.days():
        units = sum(sim.stock_units(sku, day) for sku in SKUS)
        rows.add(period, day, "Хранение", storage_fee=sim.money(units * _STORAGE_PER_UNIT))
    rows.add(period, period.date_from, "Платная приемка", acceptance=_ACCEPTANCE)
    advertising = sum((cash_spend(day, today) for day in period.days()), Decimal("0.00"))
    rows.add(
        period,
        period.date_to,
        "Удержание",
        bonus_type_name=f"Оказание услуг «WB Продвижение», документ №{period.report_id}",
        deduction=advertising,
    )
    if index % 2 == 0:
        sku = SKUS[index % len(SKUS)]
        rows.add(
            period,
            period.date_to,
            "Штраф",
            nm_id=sku.nm_id,
            sa_name=sku.vendor_code,
            subject_name=sku.subject,
            brand_name=BRAND,
            bonus_type_name=_PENALTY_REASON,
            penalty=_PENALTY,
        )


def settlement_rows(
    workspace_id: uuid.UUID, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every report header and every detail row of the demo's settlement.

    Returns:
        ``(headers, detail rows)``. Each header carries WB's own payout total,
        computed from its rows the way WB states it, so the ledger's check of
        every booked report against WB's figure agrees.
    """
    rows = _Rows(workspace_id)
    headers: list[dict[str, Any]] = []
    for index, period in enumerate(periods(today)):
        first = len(rows.rows)
        for day in period.days():
            for sku in SKUS:
                _sku_day(rows, period, sku, sim.sale_day(sku, day, today))
        _account_rows(rows, period, today, index)
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


#: Every detail column a row may leave unset, at the value WB leaves it at.
_ZERO_ROW: dict[str, Any] = {
    "nm_id": 0,
    "barcode": "",
    "sa_name": "",
    "ts_name": "",
    "srid": "",
    "office_name": "",
    "subject_name": "",
    "brand_name": "",
    "doc_type_name": "",
    "bonus_type_name": "",
    "gi_box_type_name": "",
    "delivery_method": "",
    "acquiring_bank": "",
    "payment_processing": "",
    "order_dt": None,
    "sale_dt": None,
    "quantity": 0,
    "delivery_amount": 0,
    "return_amount": 0,
    **dict.fromkeys(
        (
            "retail_price",
            "retail_amount",
            "retail_price_withdisc_rub",
            "ppvz_for_pay",
            "ppvz_vw",
            "ppvz_vw_nds",
            "ppvz_sales_commission",
            "ppvz_reward",
            "acquiring_fee",
            "delivery_rub",
            "penalty",
            "additional_payment",
            "rebill_logistic_cost",
            "storage_fee",
            "acceptance",
            "deduction",
            "sale_percent",
            "commission_percent",
            "ppvz_spp_prc",
            "ppvz_kvw_prc_base",
            "ppvz_kvw_prc",
            "acquiring_percent",
        ),
        Decimal("0"),
    ),
}
