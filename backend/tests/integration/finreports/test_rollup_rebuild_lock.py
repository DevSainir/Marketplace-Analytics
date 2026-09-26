"""A detail write waits for a rollup rebuild in flight — two real transactions.

The interleaving this guards is the one the row count cannot repair: a rebuild
snapshots the detail, an ingest commits new figures and deletes the rollup days
(which the rebuild has not committed, so there is nothing to delete), then the
rebuild commits the old figures under the same count. The advisory lock in
`repos/pnl/rollup_lock.py` makes the ingest wait instead.

Two connections on purpose: the ordinary fixture is one connection with
savepoints, and a lock cannot contend with itself.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.modules.finreports.repos import LogisticsTransactionRepository
from src.modules.finreports.repos.pnl.rollup import SettlementRollup
from src.modules.finreports.services.ingestion.columns import TXN_UPDATE

pytestmark = pytest.mark.integration

WORKSPACE = uuid.UUID("019f657a-0000-7000-8000-00000000d0c1")
DAY = date(2026, 9, 21)


def _row(rrd_id: int) -> dict[str, object]:
    """One settlement row for the lock's кабинет."""
    return {
        "rrd_id": rrd_id,
        "report_id": 900_000_001,
        "workspace_id": WORKSPACE,
        "nm_id": 1,
        "supplier_oper_name": "Продажа",
        "rr_dt": DAY,
        "currency_name": "KGS",
        "ppvz_for_pay": Decimal("100"),
    }


async def test_a_detail_write_waits_for_a_rebuild_in_flight(engine: AsyncEngine) -> None:
    """While a read is rebuilding the кабинет's rollup, an ingest cannot commit past it."""
    async with engine.connect() as reader_conn, engine.connect() as writer_conn:
        reader_tx = await reader_conn.begin()
        writer_tx = await writer_conn.begin()
        try:
            reader = AsyncSession(bind=reader_conn)
            writer = AsyncSession(bind=writer_conn)
            await LogisticsTransactionRepository(reader).bulk_upsert(
                [_row(990_001)], conflict_columns=["rrd_id"], update_columns=TXN_UPDATE
            )
            # The reader's own write took the exclusive lock; a rebuild in a
            # FRESH transaction is what a read request does, so start one.
            await reader_tx.commit()
            reader_tx = await reader_conn.begin()
            rebuilt = await SettlementRollup(reader).ensure_fresh(
                workspace_id=WORKSPACE, date_from=DAY, date_to=DAY
            )
            await writer.execute(text("SET LOCAL lock_timeout = '300ms'"))

            with pytest.raises(DBAPIError, match="lock timeout"):
                await LogisticsTransactionRepository(writer).bulk_upsert(
                    [_row(990_002)], conflict_columns=["rrd_id"], update_columns=TXN_UPDATE
                )
            assert rebuilt == 1
        finally:
            await writer_tx.rollback()
            await reader_tx.rollback()
            async with engine.begin() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM finreports.settlement_daily_rollup WHERE workspace_id = :w"),
                    {"w": WORKSPACE},
                )
                await cleanup.execute(
                    text("DELETE FROM finreports.logistics_transaction WHERE workspace_id = :w"),
                    {"w": WORKSPACE},
                )
