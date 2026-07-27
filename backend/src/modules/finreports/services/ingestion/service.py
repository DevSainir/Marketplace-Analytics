"""Write-side ingestion for ``finreports`` — flatten WB payloads into the schema.

Pure persistence (mirrors monitoring's ingestion): each method maps a list of
typed WB rows onto DB dicts and idempotently upserts them. The client-calling
orchestration (building per-workspace clients, fetching) lives in the tasks
layer, so this service stays session-bound and unit-testable.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from src.integrations.wildberries.schemas import (
    WBCard,
    WBReportDetailRow,
)
from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
)

# Column sets for the idempotent upserts (everything but the conflict key).
_TXN_UPDATE = [
    "report_id",
    "workspace_id",
    "nm_id",
    "barcode",
    "sa_name",
    "ts_name",
    "srid",
    "shk_id",
    "gi_id",
    "office_name",
    "rr_dt",
    "order_dt",
    "sale_dt",
    "supplier_oper_name",
    "bonus_type_name",
    "gi_box_type_name",
    "delivery_method",
    "currency_name",
    "quantity",
    "delivery_amount",
    "dlv_prc",
    "delivery_rub",
    "penalty",
    "additional_payment",
    "rebill_logistic_cost",
    "storage_fee",
    "acceptance",
    "deduction",
    "fix_tariff_date_from",
    "fix_tariff_date_to",
]
_REPORT_UPDATE = ["workspace_id", "date_from", "date_to", "currency", "create_dt"]
    "box_delivery_base",
    "box_delivery_liter",
    "box_delivery_coef_pct",
    "box_storage_base",
    "box_storage_liter",
    "box_storage_coef_pct",
    "geo_name",
    "dt_till_max",
]
_BASELINE_UPDATE = [
    "vendor_code",
    "length_cm",
    "width_cm",
    "height_cm",
    "weight_brutto_kg",
    "volume_l",
    "workspace_id",
    "document_proof_id",
]
_BILLED_UPDATE = [
    "nm_id",
    "barcode",
    "volume_l",
    "warehouse_coef",
    "calc_type",
    "warehouse_price",
]
_PENALTY_UPDATE = [
    "subject_name",
    "prc_over",
    "length_sup",
    "width_sup",
    "height_sup",
    "volume_sup",
    "length",
    "width",
    "height",
    "volume",
    "penalty_amount",
    "reversal_amount",
    "photo_url",
    "is_valid",
    "is_valid_dt",
    "workspace_id",
]


def _as_date(value: date | datetime | None) -> date | None:
    """Coerce a WB date/datetime (or ``None``) to a plain ``date``."""
    if isinstance(value, datetime):
        return value.date()
    return value


def _dedupe(rows: list[dict[str, object]], *, keys: list[str]) -> list[dict[str, object]]:
    """Collapse rows sharing the same conflict key, keeping the last.

    PostgreSQL's ``INSERT ... ON CONFLICT DO UPDATE`` rejects a batch that
    carries two rows with the same conflict target, so any source that emits
    storage unit) must be de-duplicated before the upsert.
    """
    by_key: dict[tuple[object, ...], dict[str, object]] = {}
    for row in rows:
        by_key[tuple(row[k] for k in keys)] = row
    return list(by_key.values())


class IngestionService:

    def __init__(
        self,
        *,
        transaction_repo: LogisticsTransactionRepository,
        report_repo: FinancialReportRepository,
    ) -> None:
        """Wire the ingestion service from the finreports repositories."""
        self._transactions = transaction_repo
        self._reports = report_repo
        self._baselines = baseline_repo
        self._billed = billed_repo
        self._penalties = penalty_repo

    async def ingest_finance_report(
        self, rows: list[WBReportDetailRow], *, workspace_id: uuid.UUID
    ) -> int:
        """Upsert settlement rows and their weekly-report headers.

        Args:
            rows: Raw ``reportDetailByPeriod`` rows.
            workspace_id: Owning workspace.

        Returns:
            The number of settlement rows upserted.
        """
        if not rows:
            return 0
        headers: dict[int, dict[str, object]] = {}
        txn_rows: list[dict[str, object]] = []
        for r in rows:
            rr = _as_date(r.rr_dt)
            header = headers.setdefault(
                r.realizationreport_id,
                {
                    "report_id": r.realizationreport_id,
                    "workspace_id": workspace_id,
                    "date_from": rr,
                    "date_to": rr,
                    "currency": r.currency_name,
                    "create_dt": None,
                },
            )
            if rr is not None:
                if header["date_from"] is None or rr < header["date_from"]:  # type: ignore[operator]
                    header["date_from"] = rr
                if header["date_to"] is None or rr > header["date_to"]:  # type: ignore[operator]
                    header["date_to"] = rr
            txn_rows.append(
                {
                    "rrd_id": r.rrd_id,
                    "report_id": r.realizationreport_id,
                    "workspace_id": workspace_id,
                    "nm_id": r.nm_id,
                    "barcode": r.barcode,
                    "sa_name": r.sa_name,
                    "ts_name": r.ts_name,
                    "srid": r.srid,
                    "shk_id": r.shk_id,
                    "gi_id": r.gi_id,
                    "office_name": r.office_name,
                    "rr_dt": rr,
                    "order_dt": _as_date(r.order_dt),
                    "sale_dt": _as_date(r.sale_dt),
                    "supplier_oper_name": r.supplier_oper_name,
                    "bonus_type_name": r.bonus_type_name,
                    "gi_box_type_name": r.gi_box_type_name,
                    "delivery_method": r.delivery_method,
                    "currency_name": r.currency_name,
                    "quantity": r.quantity,
                    "delivery_amount": r.delivery_amount,
                    "dlv_prc": r.dlv_prc,
                    "delivery_rub": r.delivery_rub,
                    "penalty": r.penalty,
                    "additional_payment": r.additional_payment,
                    "rebill_logistic_cost": r.rebill_logistic_cost,
                    "storage_fee": r.storage_fee,
                    "acceptance": r.acceptance,
                    "deduction": r.deduction,
                    "fix_tariff_date_from": _as_date(r.fix_tariff_date_from),
                    "fix_tariff_date_to": _as_date(r.fix_tariff_date_to),
                }
            )
        await self._reports.bulk_upsert(
            list(headers.values()), conflict_columns=["report_id"], update_columns=_REPORT_UPDATE
        )
        return await self._transactions.bulk_upsert(
            txn_rows, conflict_columns=["rrd_id"], update_columns=_TXN_UPDATE
        )

    async def ingest_tariffs(
    ) -> int:
        payload: list[dict[str, object]] = [
            {
                "snapshot_date": snapshot_date,
                "warehouse_name": r.warehouse_name,
                "box_delivery_base": r.box_delivery_base,
                "box_delivery_liter": r.box_delivery_liter,
                "box_delivery_coef_pct": r.box_delivery_coef_pct,
                "box_storage_base": r.box_storage_base,
                "box_storage_liter": r.box_storage_liter,
                "box_storage_coef_pct": r.box_storage_coef_pct,
                "geo_name": r.geo_name,
                "dt_till_max": dt_till_max,
            }
            for r in rows
            if r.warehouse_name
        ]
        payload = _dedupe(payload, keys=["snapshot_date", "warehouse_name"])
        return await self._tariffs.bulk_upsert(
            payload,
            conflict_columns=["snapshot_date", "warehouse_name"],
        )

    async def ingest_baselines(
        self, cards: list[WBCard], *, workspace_id: uuid.UUID, snapshot_date: date
    ) -> int:
        """Snapshot declared dimensions from content cards (skip dimensionless)."""
        payload: list[dict[str, object]] = []
        for card in cards:
            d = card.dimensions
            if d is None or d.length is None or d.width is None or d.height is None:
                continue
            volume_l = (d.length * d.width * d.height) / Decimal(1000)
            payload.append(
                {
                    "nm_id": card.nm_id,
                    "snapshot_date": snapshot_date,
                    "source": "card",
                    "vendor_code": card.vendor_code,
                    "length_cm": d.length,
                    "width_cm": d.width,
                    "height_cm": d.height,
                    "weight_brutto_kg": d.weight_brutto,
                    "volume_l": volume_l,
                    "workspace_id": workspace_id,
                    "document_proof_id": None,
                }
            )
        return await self._baselines.bulk_upsert(
            payload,
            conflict_columns=["nm_id", "snapshot_date", "source"],
            update_columns=_BASELINE_UPDATE,
        )

        payload: list[dict[str, object]] = [
            {
                "observed_date": r.observed_date,
                "warehouse_name": r.warehouse,
                "gi_id": r.gi_id,
                "chrt_id": r.chrt_id,
                "nm_id": r.nm_id,
                "barcode": r.barcode,
                "volume_l": r.volume,
                "warehouse_coef": r.warehouse_coef,
                "calc_type": r.calc_type,
                "warehouse_price": r.warehouse_price,
            }
            for r in rows
            if r.observed_date is not None and r.warehouse
        ]
        payload = _dedupe(payload, keys=["observed_date", "warehouse_name", "gi_id", "chrt_id"])
        return await self._billed.bulk_upsert(
            payload,
            conflict_columns=["observed_date", "warehouse_name", "gi_id", "chrt_id"],
            update_columns=_BILLED_UPDATE,
        )

    ) -> int:
        payload: list[dict[str, object]] = [
            {
                "nm_id": r.nm_id,
                "dim_id": r.dim_id,
                "dt_bonus": r.dt_bonus,
                "subject_name": r.subject_name,
                "prc_over": r.prc_over,
                "length_sup": r.length_sup,
                "width_sup": r.width_sup,
                "height_sup": r.height_sup,
                "volume_sup": r.volume_sup,
                "length": r.length,
                "width": r.width,
                "height": r.height,
                "volume": r.volume,
                "penalty_amount": r.penalty_amount,
                "reversal_amount": r.reversal_amount,
                "photo_url": r.photo_urls[0] if r.photo_urls else "",
                "is_valid": r.is_valid,
                "is_valid_dt": r.is_valid_dt,
                "workspace_id": workspace_id,
            }
            for r in rows
            if r.dt_bonus is not None
        ]
        payload = _dedupe(payload, keys=["nm_id", "dim_id", "dt_bonus"])
        return await self._penalties.bulk_upsert(
            payload,
            conflict_columns=["nm_id", "dim_id", "dt_bonus"],
            update_columns=_PENALTY_UPDATE,
        )
