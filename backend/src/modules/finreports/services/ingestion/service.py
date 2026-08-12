"""Write-side ingestion for ``finreports`` — flatten WB payloads into the schema.

Pure persistence (mirrors monitoring's ingestion): each method maps a list of
typed WB rows onto DB dicts and idempotently upserts them. The client-calling
orchestration (building per-workspace clients, fetching) lives in the tasks
layer, so this service stays session-bound and unit-testable.

The mapping itself lives in :mod:`.rows` and the upsert column lists in
:mod:`.columns`; what is left here is the repository choreography.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import date
from decimal import Decimal

from src.integrations.wildberries.schemas import (
    WBCard,
    WBReportDetailRow,
)
from src.modules.finreports.repos import (
    FinancialReportRepository,
    LogisticsTransactionRepository,
)
from src.modules.finreports.services.ingestion.columns import (
    BASELINE_UPDATE,
    BILLED_UPDATE,
    MEASUREMENT_UPDATE,
    PENALTY_UPDATE,
    REPORT_UPDATE,
    TXN_UPDATE,
)
from src.modules.finreports.services.ingestion.rows import (
    dedupe,
    merge_report_headers,
    number_units,
    settlement_row,
)


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
        self._measurements = measurement_repo

    async def ingest_finance_report(
        self,
        pages: AsyncGenerator[list[WBReportDetailRow], None],
        *,
        workspace_id: uuid.UUID,
    ) -> int:
        """Upsert a paginated settlement walk and its weekly-report headers.

        Consumes the pages as they arrive and writes each one before asking for
        the next, so neither this method nor its caller ever holds more than a
        page. Taking a whole window as a list is what made the peak scale with
        the seller's history — see
        :meth:`~src.integrations.wildberries.clients.finance.WBFinanceClient.iter_report_pages`.

        Every statement here goes to the caller's session and **nothing is
        committed**: the harvest's all-or-nothing property is the caller's to
        keep, and a walk that fails halfway must leave no settlement rows behind
        (a half-written settlement window is a P&L that looks right and is not).

        Args:
            pages: The paginated walk. Consumed and closed here — a walk
                abandoned mid-way (an error below) must not be left suspended
                holding its page and its socket.
            workspace_id: Owning workspace.

        Returns:
            The number of settlement rows upserted.
        """
        headers: dict[int, dict[str, object]] = {}
        total = 0
        async with aclosing(pages):
            async for page in pages:
                merge_report_headers(headers, page, workspace_id=workspace_id)
                # Re-upserting every header on every page (a handful of rows)
                # rather than only the current page's, so the last write of a
                # report's period is always the widest one seen so far.
                await self._reports.bulk_upsert(
                    list(headers.values()),
                    conflict_columns=["report_id"],
                    update_columns=REPORT_UPDATE,
                )
                total += await self._transactions.bulk_upsert(
                    # WB's cursor is exclusive, so a repeat inside one page is
                    # the only way a duplicate key can reach the statement —
                    # and ON CONFLICT DO UPDATE rejects the whole batch if one
                    # does.
                    dedupe(
                        [settlement_row(row, workspace_id=workspace_id) for row in page],
                        keys=["rrd_id"],
                    ),
                    conflict_columns=["rrd_id"],
                    update_columns=TXN_UPDATE,
                )
        return total

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
        payload = dedupe(payload, keys=["snapshot_date", "warehouse_name"])
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
            update_columns=BASELINE_UPDATE,
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
        payload = dedupe(payload, keys=["observed_date", "warehouse_name", "gi_id", "chrt_id"])
        return await self._billed.bulk_upsert(
            payload,
            conflict_columns=["observed_date", "warehouse_name", "gi_id", "chrt_id"],
            update_columns=BILLED_UPDATE,
        )

    ) -> int:

        Every row WB publishes is kept. ``(nm_id, dim_id, dt_bonus)`` is not
        unique — WB emits one row per penalised unit, and rows sharing that key
        can carry different card dimensions and penalties — so each group is
        sorted deterministically and numbered (``unit_no``). Sorting rather
        than trusting WB's page order is what makes a re-harvest idempotent:
        the same report always yields the same ordinals.
        """
        payload: list[dict[str, object]] = [
            {
                "nm_id": r.nm_id,
                "dim_id": r.dim_id,
                "dt_bonus": r.dt_bonus,
                "unit_no": 0,
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
        payload = number_units(payload)
        return await self._penalties.bulk_upsert(
            payload,
            conflict_columns=["nm_id", "dim_id", "dt_bonus", "unit_no"],
            update_columns=PENALTY_UPDATE,
        )

    ) -> int:
        payload: list[dict[str, object]] = [
            {
                "nm_id": r.nm_id,
                "dim_id": r.dim_id,
                "subject_name": r.subject_name,
                "length_cm": r.length,
                "width_cm": r.width,
                "height_cm": r.height,
                "volume_l": r.volume,
                "measured_at": r.measured_at,
                "photo_url": r.photo_urls[0] if r.photo_urls else "",
                "workspace_id": workspace_id,
            }
            for r in rows
            if r.dim_id
        ]
        payload = dedupe(payload, keys=["nm_id", "dim_id"])
        return await self._measurements.bulk_upsert(
            payload,
            conflict_columns=["nm_id", "dim_id"],
            update_columns=MEASUREMENT_UPDATE,
        )
