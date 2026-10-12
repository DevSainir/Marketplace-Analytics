"""Build WB's «Еженедельный детализированный отчет» workbook for tests.

The header row is the parser's own list of required columns, so a test file
reads exactly as WB's would; the column order is shuffled from WB's on purpose,
because the parser finds columns by name. Values default to a plain logistics
row of report 992915233's week; a test overrides only what it is about.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Any

import openpyxl

from src.modules.finreports.services.settlement_upload.workbook import REQUIRED_HEADERS

REPORT_ID = 992915233
FILENAME = f"Еженедельный детализированный отчет №{REPORT_ID}_9383646.zip"

_DEFAULTS: dict[str, Any] = {
    "Обоснование для оплаты": "Логистика",
    "Тип документа": "",
    "Код номенклатуры": 953770957,
    "Артикул поставщика": "m-trx01-blk",
    "Баркод": "2046161763178",
    "Srid": "e1.ra9e753cc5d8f4196b02f20c7b10c956b.0.0",
    "Дата продажи": "2026-10-06",
    "Дата заказа покупателем": "2026-10-01",
    "Услуги по доставке товара покупателю": 121.1,
    "Количество доставок": 1,
}


def weekly_row(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """One sheet row by header text: the defaults, with ``overrides`` on top."""
    return _DEFAULTS | (overrides or {})


def weekly_workbook(rows: list[dict[str, Any]], *, headers: list[str] | None = None) -> bytes:
    """The .xlsx WB serves: one sheet, «№» first, a header row and the rows."""
    columns = headers or ["№", *sorted(REQUIRED_HEADERS - {"№"}, reverse=True)]
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append(columns)
    for ordinal, row in enumerate(rows, start=1):
        values = {"№": ordinal, **row}
        sheet.append([values.get(column, "") for column in columns])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def weekly_zip(xlsx: bytes, *, member: str | None = None) -> bytes:
    """WB's download: a stored zip holding the one workbook, named like the zip."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(member or FILENAME.replace(".zip", " - 1.xlsx"), xlsx)
    return out.getvalue()


def week_of_992915233() -> tuple[date, date]:
    """The period those rows belong to."""
    return date(2026, 10, 5), date(2026, 10, 11)


__all__ = [
    "FILENAME",
    "REPORT_ID",
    "week_of_992915233",
    "weekly_row",
    "weekly_workbook",
    "weekly_zip",
]
