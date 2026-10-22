"""The rows of WB's weekly report, built one article-day at a time.

One row per sold unit, returned unit, delivery leg, storage day and deduction —
WB's own shapes, operation labels and sign rules, so the real P&L derivation
runs over them unchanged (``docs/finreports/PNL.md``). Which reports exist, and
their headers, is :mod:`scripts.seed_demo.settlement`.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.advertising import cash_spend
from scripts.seed_demo.catalogue import (
    BRAND,
    CURRENCY,
    RRD_ID_BASE,
    SKUS,
    WAREHOUSES,
    DemoSku,
    barcode,
    size_weight,
)
from scripts.seed_demo.economics import COMMISSION_PERCENT, sale_amounts
from src.modules.finreports.constants import REFUND_DOC_TYPE

#: What WB charges to bring a cancelled or returned unit back.
_RETURN_LEG = Decimal("50.00")
#: Storage, per unit on the warehouses, per day.
_STORAGE_PER_UNIT = Decimal("0.11")
#: Paid acceptance of the period's one supply.
_ACCEPTANCE = Decimal("1350.00")
#: A fine every other week, on the article that earned it.
_PENALTY = Decimal("500.00")
_PENALTY_REASON = "Занижение фактических габаритов упаковки товара"


class DetailRows:
    """Builds detail rows with the keys and identity every row shares.

    Every row carries every column, so a whole report goes in as one INSERT per
    chunk; ``rrd_id`` counts up from the demo's range.
    """

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self._workspace_id = workspace_id
        self._next = RRD_ID_BASE
        self.rows: list[dict[str, Any]] = []

    def add(self, report_id: int, day: date, oper: str, **fields: Any) -> None:
        """Append one row of report ``report_id``, dated ``day``, with ``fields`` set on it."""
        self._next += 1
        row: dict[str, Any] = dict(_ZERO_ROW)
        row.update(
            rrd_id=self._next,
            report_id=report_id,
            workspace_id=self._workspace_id,
            rr_dt=day,
            supplier_oper_name=oper,
            currency_name=CURRENCY,
            site_country="Россия",
        )
        row.update(fields)
        self.rows.append(row)


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


def article_day(rows: DetailRows, report_id: int, sku: DemoSku, sale: sim.SaleDay) -> None:
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
        rows.add(report_id, sale.day, "Продажа", doc_type_name="Продажа", **unit, **unit_money)
        rows.add(
            report_id,
            sale.day,
            "Логистика",
            doc_type_name="Продажа",
            bonus_type_name="К клиенту при продаже",
            delivery_amount=1,
            delivery_rub=sku.delivery,
            **unit,
        )
    for unit in _units(sku, sale, sale.returned, "return"):
        rows.add(
            report_id, sale.day, "Возврат", doc_type_name=REFUND_DOC_TYPE, **unit, **unit_money
        )
        rows.add(
            report_id,
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
                report_id,
                sale.day,
                "Логистика",
                doc_type_name="Продажа",
                bonus_type_name=reason,
                delivery_rub=cost,
                **{leg: 1},
                **unit,
            )


def account_charges(
    rows: DetailRows, report_id: int, days: list[date], today: date, fined: DemoSku | None
) -> None:
    """A period's charges no article owns: storage, acceptance, advertising — and a fine.

    Args:
        rows: Where the rows go.
        report_id: The period's report.
        days: The period's days, oldest first.
        today: The day the seed runs, which decides which campaigns had started.
        fined: The article fined this period, if any.
    """
    for day in days:
        units = sum(sim.stock_units(sku, day) for sku in SKUS)
        rows.add(report_id, day, "Хранение", storage_fee=sim.money(units * _STORAGE_PER_UNIT))
    rows.add(report_id, days[0], "Платная приемка", acceptance=_ACCEPTANCE)
    advertising = sum((cash_spend(day, today) for day in days), Decimal("0.00"))
    rows.add(
        report_id,
        days[-1],
        "Удержание",
        bonus_type_name=f"Оказание услуг «WB Продвижение», документ №{report_id}",
        deduction=advertising,
    )
    if fined is not None:
        sku = fined
        rows.add(
            report_id,
            days[-1],
            "Штраф",
            nm_id=sku.nm_id,
            sa_name=sku.vendor_code,
            subject_name=sku.subject,
            brand_name=BRAND,
            bonus_type_name=_PENALTY_REASON,
            penalty=_PENALTY,
        )


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
