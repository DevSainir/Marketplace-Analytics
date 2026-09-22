"""Pure row mappers for the ``finreports`` ingestion.

Nothing here touches a session: each function turns typed WB rows into the plain
dicts :meth:`~src.modules.finreports.repos.base.BaseRepository.bulk_upsert`
wants. Keeping the mapping pure is what lets the settlement mapping — the widest
and the one that matters most — be unit-tested against a raw WB payload without
a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from src.integrations.wildberries.schemas import WBReportDetailRow

#: Sort key that orders the rows of one penalty group reproducibly. WB publishes
#: no row identity, so the ordinal has to come from the values themselves.
_UNIT_ORDER = ("volume_sup", "penalty_amount", "reversal_amount")


def as_date(value: date | datetime | None) -> date | None:
    """Coerce a WB date/datetime (or ``None``) to a plain ``date``."""
    if isinstance(value, datetime):
        return value.date()
    return value


def dedupe(rows: list[dict[str, Any]], *, keys: list[str]) -> list[dict[str, Any]]:
    """Collapse rows sharing the same conflict key, keeping the last.

    PostgreSQL's ``INSERT ... ON CONFLICT DO UPDATE`` rejects a batch that
    carries two rows with the same conflict target, so any source that emits
    storage unit) must be de-duplicated before the upsert.
    """
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        by_key[tuple(row[k] for k in keys)] = row
    return list(by_key.values())


def _sort_value(value: object) -> Decimal:
    """Order a possibly-``None`` numeric column without comparing mixed types."""
    return value if isinstance(value, Decimal) else Decimal(-1)


def number_units(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Number the rows of each ``(nm_id, dim_id, dt_bonus)`` group.

    WB emits one row per penalised unit with no row identity, so the ordinal is
    derived from the values: each group is sorted by :data:`_UNIT_ORDER` and
    numbered from zero. A re-harvest of the same report therefore reproduces the
    same ordinals, which keeps the upsert idempotent instead of shuffling rows
    between keys.
    """
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["nm_id"], row["dim_id"], row["dt_bonus"]), []).append(row)
    numbered: list[dict[str, Any]] = []
    for group in groups.values():
        group.sort(key=lambda r: tuple(_sort_value(r.get(k)) for k in _UNIT_ORDER))
        for index, row in enumerate(group):
            row["unit_no"] = index
            numbered.append(row)
    return numbered


def settlement_row(row: WBReportDetailRow, *, workspace_id: uuid.UUID) -> dict[str, Any]:
    """Map one ``reportDetailByPeriod`` row onto ``logistics_transaction``.

    Verbatim, field for field — no arithmetic, no classification, no dropping of
    "uninteresting" operations. Everything the P&L and the claim derive is
    derived on read, so this mapping staying dumb is what lets both be corrected
    later without re-harvesting 2.5 years of settlements.
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


def report_headers(
    rows: list[WBReportDetailRow], *, workspace_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Group settlement rows into their weekly ``financial_report`` headers.

    See :func:`merge_report_headers` for why the period is taken from WB.
    """
    headers: dict[int, dict[str, Any]] = {}
    merge_report_headers(headers, rows, workspace_id=workspace_id)
    return list(headers.values())


def merge_report_headers(
    headers: dict[int, dict[str, Any]],
    rows: Sequence[WBReportDetailRow],
    *,
    workspace_id: uuid.UUID,
) -> None:
    """Fold one page of settlement rows into the headers accumulated so far.

    The period comes from WB's own ``date_from``/``date_to`` on the row, not from
    ``min(rr_dt)``/``max(rr_dt)``: a report routinely carries no settlement on
    its first or last day, and deriving the period from the rows then reports a
    six-day week — which shifts every week-scoped figure the P&L and the claim
    put in front of a court. ``rr_dt`` is kept only as the fallback for the rare
    row where WB leaves the period blank.

    That fallback is exactly why the accumulator is threaded through the whole
    paginated walk instead of each page building its own headers: a report whose
    rows straddle a page boundary would otherwise have its period rebuilt from
    the last page's ``rr_dt`` alone, and the upsert would overwrite the wider
    period with the narrower one. The dict is tiny — one entry per weekly
    report, a handful per harvest window — so carrying it costs nothing.

    Args:
        headers: Accumulator, keyed by ``realizationreport_id``. Mutated.
        rows: One page of settlement rows.
        workspace_id: Owning workspace.
    """
    for row in rows:
        stated_from, stated_to = as_date(row.date_from), as_date(row.date_to)
        rr = as_date(row.rr_dt)
        header = headers.setdefault(
            row.realizationreport_id,
            {
                "report_id": row.realizationreport_id,
                "workspace_id": workspace_id,
                "date_from": stated_from or rr,
                "date_to": stated_to or rr,
                "currency": row.currency_name,
                "create_dt": as_date(row.create_dt),
            },
        )
        header["date_from"] = _earliest(header["date_from"], stated_from or rr)
        header["date_to"] = _latest(header["date_to"], stated_to or rr)
        if header["create_dt"] is None:
            header["create_dt"] = as_date(row.create_dt)
        if not header["currency"]:
            header["currency"] = row.currency_name


def _earliest(current: date | None, candidate: date | None) -> date | None:
    """Return the earlier of two optional dates."""
    if candidate is None:
        return current
    return candidate if current is None or candidate < current else current


def _latest(current: date | None, candidate: date | None) -> date | None:
    """Return the later of two optional dates."""
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


__all__ = [
    "as_date",
    "dedupe",
    "merge_report_headers",
    "number_units",
    "report_headers",
    "settlement_row",
]
