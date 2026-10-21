"""Pure row mappers for the ``finreports`` ingestion.

Nothing here touches a session: each function turns typed WB rows into the plain
dicts :meth:`~src.modules.finreports.repos.base.BaseRepository.bulk_upsert`
wants. Keeping the mapping pure is what lets the settlement mapping — the widest
and the one that matters most — be unit-tested against a raw WB payload without
a database.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from src.integrations.wildberries.schemas import WBReportDetailRow


def as_date(value: date | datetime | None) -> date | None:
    """Coerce a WB date/datetime (or ``None``) to a plain ``date``."""
    if isinstance(value, datetime):
        return value.date()
    return value


def dedupe(rows: list[dict[str, Any]], *, keys: list[str]) -> list[dict[str, Any]]:
    """Collapse rows sharing the same conflict key, keeping the last.

    PostgreSQL's ``INSERT ... ON CONFLICT DO UPDATE`` rejects a batch that
    carries two rows with the same conflict target, so any source that can emit
    several rows per key (a settlement page repeating an ``rrd_id``) must be
    de-duplicated before the upsert.
    """
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        by_key[tuple(row[k] for k in keys)] = row
    return list(by_key.values())


def settlement_row(row: WBReportDetailRow, *, workspace_id: uuid.UUID) -> dict[str, Any]:
    """Map one settlement row onto ``logistics_transaction``.

    The row arrives as :class:`WBFinanceReportRow` from finance-api; its aliases
    give it the ``reportDetailByPeriod`` field names this function reads.

    Verbatim, field for field — no arithmetic, no classification, no dropping of
    "uninteresting" operations. Everything the P&L derives is derived on read,
    so this mapping staying dumb is what lets it be corrected later without
    re-harvesting 2.5 years of settlements.
    """
    return {
        "rrd_id": row.rrd_id,
        "report_id": row.realizationreport_id,
        "workspace_id": workspace_id,
        "nm_id": row.nm_id,
        "barcode": row.barcode,
        "sa_name": row.sa_name,
        "ts_name": row.ts_name,
        "srid": row.srid,
        "shk_id": row.shk_id,
        "gi_id": row.gi_id,
        "office_name": row.office_name,
        "subject_name": row.subject_name,
        "brand_name": row.brand_name,
        "rr_dt": as_date(row.rr_dt),
        "order_dt": as_date(row.order_dt),
        "sale_dt": as_date(row.sale_dt),
        "supplier_oper_name": row.supplier_oper_name,
        "doc_type_name": row.doc_type_name,
        "bonus_type_name": row.bonus_type_name,
        "gi_box_type_name": row.gi_box_type_name,
        "delivery_method": row.delivery_method,
        "currency_name": row.currency_name,
        "site_country": row.site_country,
        "srv_dbs": row.srv_dbs,
        "quantity": row.quantity,
        "delivery_amount": row.delivery_amount,
        "return_amount": row.return_amount,
        "retail_price": row.retail_price,
        "retail_amount": row.retail_amount,
        "retail_price_withdisc_rub": row.retail_price_withdisc_rub,
        "sale_percent": row.sale_percent,
        "commission_percent": row.commission_percent,
        "ppvz_for_pay": row.ppvz_for_pay,
        "ppvz_vw": row.ppvz_vw,
        "ppvz_vw_nds": row.ppvz_vw_nds,
        "ppvz_sales_commission": row.ppvz_sales_commission,
        "ppvz_reward": row.ppvz_reward,
        "ppvz_spp_prc": row.ppvz_spp_prc,
        "ppvz_kvw_prc_base": row.ppvz_kvw_prc_base,
        "ppvz_kvw_prc": row.ppvz_kvw_prc,
        "acquiring_fee": row.acquiring_fee,
        "acquiring_percent": row.acquiring_percent,
        "acquiring_bank": row.acquiring_bank,
        "payment_processing": row.payment_processing,
        "product_discount_for_report": row.product_discount_for_report,
        "supplier_promo": row.supplier_promo,
        "seller_promo_discount": row.seller_promo_discount,
        "loyalty_discount": row.loyalty_discount,
        "installment_cofinancing_amount": row.installment_cofinancing_amount,
        "cashback_amount": row.cashback_amount,
        "cashback_discount": row.cashback_discount,
        "cashback_commission_change": row.cashback_commission_change,
        "agency_vat": row.agency_vat,
        "dlv_prc": row.dlv_prc,
        "delivery_rub": row.delivery_rub,
        "penalty": row.penalty,
        "additional_payment": row.additional_payment,
        "rebill_logistic_cost": row.rebill_logistic_cost,
        "storage_fee": row.storage_fee,
        "acceptance": row.acceptance,
        "deduction": row.deduction,
        "fix_tariff_date_from": as_date(row.fix_tariff_date_from),
        "fix_tariff_date_to": as_date(row.fix_tariff_date_to),
    }


__all__ = [
    "as_date",
    "dedupe",
    "settlement_row",
]
