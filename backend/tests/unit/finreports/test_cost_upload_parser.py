"""The upload parser reads three formats and trusts only two columns.

The export is one shape, but a seller may hand it back as .xlsx, legacy .xls, or
a .csv from Excel/1C. Each is read by a different library; all must find «Артикул
WB» and «Себестоимость за 1 ед.» by name — reorder-, encoding- and
delimiter-tolerant — and reject a file that is not a cost sheet at all rather
than guess a wrong column (PNL.md §13).
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
import xlwt
from openpyxl import Workbook

from src.core.exceptions import ValidationError
from src.modules.finreports.services.cost_upload_parser import parse_cost_upload


def _xlsx(rows: list[list[object]]) -> bytes:
    """An .xlsx workbook from a list of rows (first row is the header)."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _xls(rows: list[list[object]]) -> bytes:
    """A legacy .xls workbook from a list of rows."""
    book = xlwt.Workbook()
    sheet = book.add_sheet("Sheet1")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_xlsx_matches_the_key_and_cost_by_header_name() -> None:
    # Arrange: columns deliberately reordered, with the total-cost column present.
    data = _xlsx(
        [
            ["Продажи", "Себестоимость, итого", "Артикул WB", "Себестоимость за 1 ед."],
            [900, 5600, 222, 700],
            [900, None, 333, None],
        ]
    )

    # Act.
    parsed = parse_cost_upload("pnl.xlsx", data)

    # Assert: keyed on «Артикул WB», cost read from the per-unit column (not итого).
    by_nm = {int(p.nm_id_raw): p for p in parsed}
    assert Decimal(str(by_nm[222].cost_raw)) == Decimal("700")
    assert by_nm[333].cost_raw is None


def test_a_legacy_xls_is_read() -> None:
    # Arrange.
    data = _xls([["Артикул WB", "Себестоимость за 1 ед."], [222, 812.5]])

    # Act.
    parsed = parse_cost_upload("prices.xls", data)

    # Assert.
    assert int(parsed[0].nm_id_raw) == 222
    assert Decimal(str(parsed[0].cost_raw)) == Decimal("812.5")


def test_a_semicolon_cp1251_csv_is_read() -> None:
    # Arrange: a Russian-Excel CSV — semicolon delimiter, Windows-1251 encoding.
    text = "Артикул WB;Себестоимость за 1 ед.\r\n222;700\r\n333;\r\n"
    data = text.encode("cp1251")

    # Act.
    parsed = parse_cost_upload("prices.csv", data)

    # Assert.
    by_nm = {int(p.nm_id_raw): p for p in parsed}
    assert by_nm[222].cost_raw == "700"
    assert by_nm[333].cost_raw in (None, "")


def test_a_bare_nm_id_header_still_matches() -> None:
    # Arrange: a minimal hand-made sheet using «nm_id» and a plain «Себестоимость».
    data = _xlsx([["nm_id", "Себестоимость"], [222, 700]])

    # Act.
    parsed = parse_cost_upload("hand.xlsx", data)

    # Assert.
    assert int(parsed[0].nm_id_raw) == 222
    assert Decimal(str(parsed[0].cost_raw)) == Decimal("700")


def test_the_format_is_detected_from_content_when_the_name_lies() -> None:
    # Arrange: real .xlsx bytes under a .csv name.
    data = _xlsx([["Артикул WB", "Себестоимость за 1 ед."], [222, 700]])

    # Act: the ZIP signature wins over the misleading extension.
    parsed = parse_cost_upload("mislabelled.csv", data)

    # Assert.
    assert int(parsed[0].nm_id_raw) == 222


def test_a_sheet_without_the_required_columns_is_rejected() -> None:
    # Arrange: a valid workbook that is not ours.
    data = _xlsx([["товар", "цена"], ["куртка", 500]])

    # Act / Assert.
    with pytest.raises(ValidationError):
        parse_cost_upload("other.xlsx", data)


def test_unreadable_bytes_are_rejected() -> None:
    # Act / Assert: raw text claiming to be xlsx is not a workbook.
    with pytest.raises(ValidationError):
        parse_cost_upload("broken.xlsx", b"this is not a workbook")
