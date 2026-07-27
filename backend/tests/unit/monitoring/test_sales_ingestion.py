"""Unit tests for the per-item sale/return ingestion (sale-date buyouts)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.integrations.wildberries.schemas import WBSaleRecord
from src.modules.monitoring.services.ingestion import IngestionService


class _CapturingSaleRepo:
    """Stands in for SaleRepository, recording the rows it is asked to upsert."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def upsert_many(self, rows: list[dict[str, Any]]) -> int:
        self.rows = rows
        return len(rows)


def _service(sale_repo: Any) -> IngestionService:
    """Build an IngestionService with only the sale repo wired (others unused)."""
    return IngestionService(
        funnel_repo=None,  # type: ignore[arg-type]
        advertising_repo=None,  # type: ignore[arg-type]
        stock_repo=None,  # type: ignore[arg-type]
        campaign_repo=None,  # type: ignore[arg-type]
        product_card_repo=None,  # type: ignore[arg-type]
        product_size_repo=None,  # type: ignore[arg-type]
        advertising_search_repo=None,  # type: ignore[arg-type]
        price_repo=None,  # type: ignore[arg-type]
        sale_repo=sale_repo,
    )


def _record(
    sale_id: str,
    *,
    changed: str = "2026-07-12T10:00:00",
    sold: str = "2026-07-12T09:00:00",
    finished: float = 4181.0,
) -> WBSaleRecord:
    """Build a raw sale record as the statistics client would parse it."""
    return WBSaleRecord.model_validate(
        {
            "saleID": sale_id,
            "srid": f"srid-{sale_id}",
            "nmId": 995716075,
            "date": sold,
            "lastChangeDate": changed,
            "priceWithDisc": 4180.8,
            "finishedPrice": finished,
            "forPay": 3100.5,
        }
    )


async def test_ingest_sales_maps_fields_and_flags_returns() -> None:
    """Rows carry the sale DATE, is_return from the R prefix, and the prices."""
    repo = _CapturingSaleRepo()

    count = await _service(repo).ingest_sales(
        [_record("S123"), _record("R456", sold="2026-07-11T15:30:00")]
    )

    assert count == 2
    by_id = {row["sale_id"]: row for row in repo.rows}
    sale = by_id["S123"]
    assert sale["nm_id"] == 995716075
    assert str(sale["sale_date"]) == "2026-07-12"
    assert sale["is_return"] is False
    assert sale["finished_price"] == 4181.0
    assert sale["last_change_date"] == datetime(2026, 7, 12, 10, 0, 0)
    ret = by_id["R456"]
    assert ret["is_return"] is True
    assert str(ret["sale_date"]) == "2026-07-11"


async def test_ingest_sales_dedupes_by_sale_id_keeping_latest_change() -> None:
    """A batch repeating one sale_id keeps the record with the newest change stamp."""
    repo = _CapturingSaleRepo()

    count = await _service(repo).ingest_sales(
        [
            _record("S123", changed="2026-07-12T10:00:00", finished=4181.0),
            _record("S123", changed="2026-07-13T08:00:00", finished=4000.0),
            _record("S123", changed="2026-07-11T23:00:00", finished=4300.0),
        ]
    )

    assert count == 1
    assert repo.rows[0]["finished_price"] == 4000.0
    assert repo.rows[0]["last_change_date"] == datetime(2026, 7, 13, 8, 0, 0)
