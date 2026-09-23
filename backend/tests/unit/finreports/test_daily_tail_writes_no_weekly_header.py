"""The provisional daily lane must not write into the settled bookkeeping.

The daily and weekly reports are the same rows — measured over 14.09-20.09 on
«Демо», 4 424 rows sharing their ``rrdId`` one for one — so the rows belong in
``logistics_transaction`` like any others and the P&L reads them by ``rr_dt``
with nothing else to change.

The **headers** are a different matter, and this is the failure this module
exists to make unrepresentable. ``financial_report`` is where the weekly
machinery reads «how far is this workspace settled» from, as
``max(date_to)``. A daily header for yesterday would answer that question with
yesterday, the freshness gate would conclude WB can have formed nothing it does
not already hold, and the weekly report would never be asked for again — the P&L
would then be built for ever out of provisional days nobody re-checks.

Nothing about that would look like an error: the counters move, the task
succeeds, and a plausible statement is exactly the failure
``docs/finreports/PNL.md`` warns about.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import pytest

from src.integrations.wildberries.schemas.finance import WBReportDetailRow
from src.modules.finreports.services.ingestion.service import IngestionService

pytestmark = pytest.mark.unit

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: A real daily report id's shape: `{supplier}{YYYYMMDD}`, fifteen digits.
_DAILY_REPORT_ID = 938364620260922
_RRD_BASE = 3_135_239_758_000


class _RecordingRepo:
    """Captures what a repository was asked to upsert, in order."""

    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []

    async def bulk_upsert(
        self,
        rows: Sequence[dict[str, Any]],
        *,
        conflict_columns: Sequence[str],
        update_columns: Sequence[str],
    ) -> int:
        """Record the batch and report it as written."""
        self.batches.append([dict(row) for row in rows])
        return len(rows)


def _ingestion(transactions: Any, reports: Any) -> IngestionService:
    """An ingestion service wired to fakes for the two repos this path uses."""
    unused: Any = None
    return IngestionService(
        transaction_repo=transactions,
        report_repo=reports,
        baseline_repo=unused,
        billed_repo=unused,
        penalty_repo=unused,
        measurement_repo=unused,
    )


async def _pages(*pages: list[dict[str, Any]]) -> AsyncGenerator[list[WBReportDetailRow], None]:
    """Yield raw rows as validated pages, the way the client does."""
    for page in pages:
        yield [WBReportDetailRow.model_validate(row) for row in page]


def _row(index: int) -> dict[str, Any]:
    """One raw WB settlement row from a daily report."""
    return {
        "rrd_id": _RRD_BASE + index,
        "realizationreport_id": _DAILY_REPORT_ID,
        "rr_dt": "2026-09-22",
        "currency_name": "KGS",
    }


async def test_the_daily_lane_writes_rows_and_no_report_header() -> None:
    """The rows land; `financial_report` is not touched at all."""
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    written = await _ingestion(transactions, reports).ingest_settlement_rows(
        _pages([_row(1), _row(2)]), workspace_id=_WORKSPACE
    )

    assert written == 2
    assert [row["rrd_id"] for batch in transactions.batches for row in batch] == [
        _RRD_BASE + 1,
        _RRD_BASE + 2,
    ]
    assert reports.batches == [], (
        "A daily header in `financial_report` would move `latest_settled_date` to "
        "yesterday and the weekly report would stop being asked for."
    )


async def test_the_daily_rows_carry_the_daily_report_id() -> None:
    """The row keeps WB's own id, so the tail's bookkeeping can find it again.

    That id is what
    :meth:`~src.modules.finreports.repos.daily_settlement.DailySettlementRepository.fingerprint`
    aggregates over, and it is fifteen digits wide — a column narrower than
    BigInteger would have truncated it.
    """
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    await _ingestion(transactions, reports).ingest_settlement_rows(
        _pages([_row(1)]), workspace_id=_WORKSPACE
    )

    assert transactions.batches[0][0]["report_id"] == _DAILY_REPORT_ID


async def test_the_settled_lane_still_writes_both() -> None:
    """The guard above must not have cost the weekly lane its headers."""
    transactions, reports = _RecordingRepo(), _RecordingRepo()

    await _ingestion(transactions, reports).ingest_finance_report(
        _pages([_row(1)]), workspace_id=_WORKSPACE
    )

    assert transactions.batches, "the weekly lane still writes rows"
    assert reports.batches, "and still writes the report header it is the source of"
