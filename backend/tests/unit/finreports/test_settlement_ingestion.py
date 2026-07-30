"""Unit tests for the settlement-row ingestion mapping.

The mapping is dumb by design, which makes it exactly the place where a column
goes missing without anything failing. Two silent-corruption modes are pinned
here because neither surfaces as an error:

* **A column absent from the upsert's ``update_columns``** keeps its OLD value
  when a report is re-harvested. A full re-fetch then reports "436 742 rows
  written" while every new column stays at its ``ALTER TABLE`` default of zero —
  which is precisely what a P&L with no revenue looks like.
* **A column absent from the row mapper** is never written at all.

The third test covers the report period, which WB states explicitly and which we
used to derive from ``min(rr_dt)``/``max(rr_dt)`` instead.
"""

from __future__ import annotations

import uuid
from datetime import date

from src.integrations.wildberries.schemas import WBReportDetailRow
from src.modules.finreports.models import LogisticsTransaction
from src.modules.finreports.services.ingestion.columns import TXN_UPDATE
from src.modules.finreports.services.ingestion.rows import report_headers, settlement_row

#: Not overwritten on conflict: the conflict key itself, and a server default.
_NOT_UPDATED = {"rrd_id", "created_at"}

_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")


def _model_columns() -> set[str]:
    """Every column the settlement table declares."""
    return {column.name for column in LogisticsTransaction.__table__.columns}


def test_every_column_is_overwritten_when_a_report_is_reharvested() -> None:
    """``TXN_UPDATE`` covers the whole table bar the key and the server default.

    A column missing here survives a re-harvest with its stale value, and
    ``bulk_upsert`` returns the number of rows *submitted*, so the run reports
    success either way.
    """
    assert _model_columns() - set(TXN_UPDATE) == _NOT_UPDATED
    assert set(TXN_UPDATE) - _model_columns() == set()
    assert len(TXN_UPDATE) == len(set(TXN_UPDATE))


def test_the_mapper_writes_every_column_the_table_declares() -> None:
    """A minimal WB row still produces a value for every column but ``created_at``."""
    mapped = settlement_row(WBReportDetailRow(rrd_id=1), workspace_id=_WORKSPACE)

    assert _model_columns() - set(mapped) == {"created_at"}
    assert set(mapped) - _model_columns() == set()


def test_wb_omitted_fields_do_not_break_the_mapping() -> None:
    """WB omits keys rather than sending null; the mapping must tolerate it.

    ``bonus_type_name`` is absent from 1 318 of 7 097 rows in one live report and
    ``kiz`` from 99. Modelling any of them as required turns a normal report into
    a harvest failure.
    """
    mapped = settlement_row(
        WBReportDetailRow.model_validate({"rrd_id": 7, "nm_id": 42}), workspace_id=_WORKSPACE
    )

    assert mapped["bonus_type_name"] == ""
    assert mapped["nm_id"] == 42
    assert mapped["retail_amount"] == 0


def test_counts_are_kept_apart_from_money() -> None:
    """``delivery_amount``/``return_amount`` are carried as the counts they are.

    Exactly one of them is 1 on a «Логистика» row, and that is what splits
    ``delivery_rub`` into forward and return legs. Reading either as ₽ doubles
    the logistics line.
    """
    row = WBReportDetailRow.model_validate(
        {"rrd_id": 3, "delivery_amount": 0, "return_amount": 1, "delivery_rub": "59.27"}
    )

    mapped = settlement_row(row, workspace_id=_WORKSPACE)

    assert mapped["delivery_amount"] == 0
    assert mapped["return_amount"] == 1
    assert str(mapped["delivery_rub"]) == "59.27"


def test_the_report_period_comes_from_wb_not_from_the_settled_days() -> None:
    """The header uses WB's own ``date_from``/``date_to``, not min/max ``rr_dt``.

    A report routinely settles nothing on its first or last day. Deriving the
    period from the rows then publishes a six-day «week», which shifts every
    week-scoped figure on the statement and in the claim.
    """
    rows = [
        WBReportDetailRow.model_validate(
            {
                "rrd_id": 1,
                "realizationreport_id": 969371534,
                "date_from": "2026-07-13",
                "date_to": "2026-07-19",
                "create_dt": "2026-07-20",
                "rr_dt": "2026-07-15",
                "currency_name": "KGS",
            }
        ),
        WBReportDetailRow.model_validate(
            {
                "rrd_id": 2,
                "realizationreport_id": 969371534,
                "date_from": "2026-07-13",
                "date_to": "2026-07-19",
                "rr_dt": "2026-07-17",
                "currency_name": "KGS",
            }
        ),
    ]

    headers = report_headers(rows, workspace_id=_WORKSPACE)

    assert len(headers) == 1
    assert headers[0]["date_from"] == date(2026, 7, 13)
    assert headers[0]["date_to"] == date(2026, 7, 19)
    assert headers[0]["create_dt"] == date(2026, 7, 20)


def test_a_report_with_no_stated_period_falls_back_to_its_settlement_dates() -> None:
    """WB leaving the period blank must not produce a header with no period at all."""
    rows = [
        WBReportDetailRow.model_validate(
            {"rrd_id": 1, "realizationreport_id": 900, "rr_dt": "2026-07-15"}
        )
    ]

    headers = report_headers(rows, workspace_id=_WORKSPACE)

    assert headers[0]["date_from"] == date(2026, 7, 15)
    assert headers[0]["date_to"] == date(2026, 7, 15)


def test_ppvz_vw_keeps_the_precision_wb_publishes() -> None:
    """WB serves ``ppvz_vw`` unrounded; rounding it breaks the payout identity.

    It is a VAT-inclusive reward divided by 1.12, so it carries ~14 decimals.
    Stored at 2 decimals it becomes bit-identical to ``ppvz_sales_commission``
    and the identity fails on ~2 % of rows.
    """
    column = LogisticsTransaction.__table__.columns["ppvz_vw"]

    assert column.type.scale is not None
    assert column.type.scale >= 6
