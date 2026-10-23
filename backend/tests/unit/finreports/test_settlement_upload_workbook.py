"""Reading WB's weekly report file — what it accepts, what it refuses, how it maps.

The mapping itself was checked against a complete WB weekly report file (all 58
columns agreeing with the API's rows on every row); these pin the
behaviour around it — the refusals and the cells the file writes differently.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.core.calendar_words import day_text, period_text
from src.core.exceptions import ValidationError
from src.modules.finreports.services.settlement_upload.compare import RowSet, difference
from src.modules.finreports.services.settlement_upload.wording import rows_text
from src.modules.finreports.services.settlement_upload.workbook import (
    HEADER_FOR,
    iter_report_rows,
    open_upload,
)
from tests.support import wb_labels as wb
from tests.support.wb_weekly_report import (
    FILENAME,
    REPORT_ID,
    weekly_row,
    weekly_workbook,
    weekly_zip,
)

pytestmark = pytest.mark.unit


def test_wbs_zip_is_unwrapped_and_the_report_number_read_from_its_name() -> None:
    """The seller uploads what WB handed them: a zip named "…№992915233_…"."""
    xlsx = weekly_workbook([weekly_row()])

    opened = open_upload(FILENAME, weekly_zip(xlsx))

    assert (opened.report_id, opened.xlsx) == (REPORT_ID, xlsx)


def test_the_bare_workbook_is_accepted_too() -> None:
    """Some sellers unpack the zip first; the .xlsx carries the same name."""
    xlsx = weekly_workbook([weekly_row()])

    opened = open_upload(FILENAME.replace(".zip", " - 1.xlsx"), xlsx)

    assert opened.report_id == REPORT_ID


def test_a_file_renamed_past_its_number_is_refused_with_the_reason() -> None:
    """The number is only in the name; without it the rows cannot be placed in a report."""
    xlsx = weekly_workbook([weekly_row()])

    with pytest.raises(ValidationError, match="No report number"):
        open_upload("report.xlsx", xlsx)


def test_something_that_is_not_an_archive_is_refused() -> None:
    """A CSV or a photo is not WB's report, whatever its name says."""
    with pytest.raises(ValidationError, match="Couldn't read"):
        open_upload(FILENAME, b"nm_id,cost\n1,2\n")


def test_a_sheet_without_wbs_columns_is_not_a_report() -> None:
    """A cost sheet or any other workbook fails on its headers, before a row is read."""
    xlsx = weekly_workbook([{"WB ID": 1}], headers=["WB ID", "Cost price per unit"])

    with pytest.raises(ValidationError, match="isn't a WB detailed report"):
        list(iter_report_rows(xlsx))


def test_a_cut_or_edited_file_is_refused_on_its_numbering() -> None:
    """WB numbers every row from 1; a gap means rows were removed by hand."""
    xlsx = weekly_workbook([weekly_row(), weekly_row(), weekly_row({"№": 7})])

    with pytest.raises(ValidationError, match="out of sequence"):
        list(iter_report_rows(xlsx))


def test_blank_ids_read_the_way_the_api_stores_them() -> None:
    """No supply is NULL in the API's row and no barcode is 0 — the comparison depends on it."""
    xlsx = weekly_workbook([weekly_row({HEADER_FOR["gi_id"]: "", HEADER_FOR["shk_id"]: ""})])

    (row,) = iter_report_rows(xlsx)

    assert (row["gi_id"], row["shk_id"]) == (None, 0)


def test_the_wb_reward_keeps_the_ten_places_the_api_value_has() -> None:
    """The file writes a full float; stored, the API's value is cut to ten places."""
    xlsx = weekly_workbook([weekly_row({HEADER_FOR["ppvz_vw"]: 74.77678571428571})])

    (row,) = iter_report_rows(xlsx)

    assert row["ppvz_vw"] == Decimal("74.7767857143")


def test_rows_differing_only_in_dates_are_the_same_rows() -> None:
    """The file's dates are Moscow days and the API's a day earlier on ~7 % of rows."""
    file = RowSet.of([{"srid": "a", "ppvz_for_pay": "10.00", "sale_dt": "2026-10-05"}])
    ours = RowSet.of([{"srid": "a", "ppvz_for_pay": Decimal(10), "sale_dt": "2026-10-04"}])

    assert difference(file, ours).same


def test_a_row_wb_issued_twice_is_two_rows() -> None:
    """Multisets, not sets: two identical logistics charges are two charges."""
    row = {"srid": "a", "delivery_rub": "46.75"}

    diff = difference(RowSet.of([row, row]), RowSet.of([row]))

    assert diff.file_extends_ours


def test_a_refund_counts_against_the_payout() -> None:
    """WB's forPaySum negates refund rows; the upload's total must agree with it."""
    rows = RowSet.of(
        [
            {"ppvz_for_pay": "100.00", "doc_type_name": wb.SALE},
            {"ppvz_for_pay": "30.00", "doc_type_name": wb.REFUND},
        ]
    )

    assert rows.for_pay == Decimal("70.00")


def test_the_seller_reads_a_period_day_first_and_a_real_plural() -> None:
    """The period, the day and the row count read as they do on the page."""
    assert period_text(date(2026, 10, 5), date(2026, 10, 11)) == "5–11 Oct 2026"
    assert period_text(date(2026, 9, 28), date(2026, 10, 4)) == "28 Sep – 4 Oct 2026"
    assert period_text(date(2025, 12, 29), date(2026, 1, 4)) == "29 Dec 2025 – 4 Jan 2026"
    assert period_text(date(2026, 8, 31), date(2026, 8, 31)) == "31 Aug 2026"
    assert day_text(date(2026, 10, 22)) == "22 Oct 2026"
    assert rows_text(3257) == "3,257 rows"
    assert rows_text(1) == "1 row"
