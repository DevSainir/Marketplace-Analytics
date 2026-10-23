"""The cost-price importer's business rules, against fake repositories.

The parser (``test_cost_price_workbook``) proves a file becomes rows; this
proves what the service *does* with those rows, which is where a hand-edited
spreadsheet could poison the P&L. Each rule from ``import_workbook`` is pinned:

* a cost lands only on a SKU the workspace already knows;
* it is stored in the workspace's settlement currency, never the file's;
* a blank cost price changes nothing (a downloaded file is mostly blanks);
* a non-numeric or out-of-range value is reported, not silently dropped;
* a SKU listed twice cannot blow up the upsert batch.

The fakes stand in for the two repositories the service composes, so the test
touches no database and the assertions are about behaviour, not SQL.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

from openpyxl import Workbook

from src.modules.finreports.repos.pnl.aggregate import SkuUnits
from src.modules.finreports.services.cost_price import CostPriceService

WORKSPACE = uuid.uuid4()


class _FakeCostRepo:
    """Records upserts; starts with no costs on file."""

    def __init__(self) -> None:
        self.upserted: list[dict[str, object]] = []

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[object]:
        return []

    async def upsert_many(self, rows: list[dict[str, object]]) -> int:
        self.upserted = list(rows)
        return len(rows)


class _FakePnlRepo:
    """Reports a fixed set of SKUs as having sold, for the coverage list."""

    def __init__(self, sold: list[SkuUnits]) -> None:
        self._sold = sold

    async def sku_units(self, **_: object) -> list[SkuUnits]:
        return self._sold


def _service(sold_nm_ids: list[int]) -> tuple[CostPriceService, _FakeCostRepo]:
    """A service whose known universe is exactly ``sold_nm_ids``."""
    cost_repo = _FakeCostRepo()
    sold = [
        SkuUnits(nm_id=nm, vendor_code=f"art-{nm}", sold_units=10, returned_units=0)
        for nm in sold_nm_ids
    ]
    service = CostPriceService(cost_repo=cost_repo, pnl_repo=_FakePnlRepo(sold))  # type: ignore[arg-type]
    return service, cost_repo


def _upload(rows: list[tuple[object, object]]) -> bytes:
    """A minimal cost sheet: ("WB ID", "Cost price per unit") data rows."""
    wb = Workbook()
    ws = wb.active
    ws.append(["WB ID", "Cost price per unit"])
    for nm_id, cost in rows:
        ws.append([nm_id, cost])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def test_a_cost_lands_on_a_known_sku() -> None:
    # Arrange: nm 111 has sold; the file prices it.
    service, cost_repo = _service([111])
    data = _upload([(111, 700)])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: one cost written, scoped to the caller's workspace and marked manual.
    assert result.applied == 1
    assert result.skipped == 0
    written = cost_repo.upserted[0]
    assert written["nm_id"] == 111
    assert written["cost"] == Decimal("700")
    assert written["workspace_id"] == WORKSPACE
    assert written["source"] == "manual"
    assert written["currency"] == "KGS"


async def test_an_unknown_sku_is_reported_not_inserted() -> None:
    # Arrange: the file prices a SKU that never sold here.
    service, cost_repo = _service([111])
    data = _upload([(999, 500)])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: nothing written, one issue naming the row and SKU.
    assert result.applied == 0
    assert cost_repo.upserted == []
    assert result.issues[0].nm_id == 999


async def test_a_blank_cost_changes_nothing_without_an_issue() -> None:
    # Arrange: a known SKU with an empty cost price (the common case).
    service, cost_repo = _service([111])
    data = _upload([(111, None)])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: skipped, but not flagged as a problem.
    assert result.applied == 0
    assert result.skipped == 1
    assert result.issues == []
    assert cost_repo.upserted == []


async def test_a_non_numeric_cost_is_reported() -> None:
    # Arrange: a known SKU whose cost cell is text.
    service, _ = _service([111])
    data = _upload([(111, "expensive")])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: not applied, and the reason points at the row.
    assert result.applied == 0
    assert result.issues[0].row == 2


async def test_a_negative_cost_is_rejected() -> None:
    # Arrange: a known SKU priced below zero — the validator's floor.
    service, cost_repo = _service([111])
    data = _upload([(111, -5)])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: rejected, nothing written.
    assert result.applied == 0
    assert cost_repo.upserted == []
    assert result.issues


async def test_a_sku_listed_twice_keeps_the_last_and_reports_the_duplicate() -> None:
    # Arrange: two rows for one known SKU.
    service, cost_repo = _service([111])
    data = _upload([(111, 700), (111, 800)])

    # Act.
    result = await service.import_workbook(workspace_id=WORKSPACE, filename="pnl.xlsx", data=data)

    # Assert: a single upsert (the last value), and the duplicate is flagged.
    assert result.applied == 1
    assert cost_repo.upserted[0]["cost"] == Decimal("800")
    assert any("twice" in issue.reason for issue in result.issues)
