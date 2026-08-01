"""Read an uploaded cost sheet back into per-row cells, in any of three formats.

The export hands out one shape (``build_pnl_workbook``); a seller may upload it
back as **.xlsx**, the legacy **.xls**, or a **.csv** exported from Excel or 1C.
Each reader is a different library, but all three converge on the same job: find
the two columns that matter and return every data row.

Only two columns are trusted, located **by header name** so the seller may
reorder, delete, or annotate the rest and the upload still lands:

* **«Артикул WB»** (or a bare ``nm_id``) — the join key. Nothing else identifies
  a SKU safely (PNL.md §13).
* **«Себестоимость за 1 ед.»** — the one figure read back. Matched loosely
  (contains «себестоимость» and «ед»), with a plain «Себестоимость» as a
  fallback for a minimal hand-made sheet.

What the parser will not do is guess: a file with no recognisable key or cost
header is rejected outright, and per-cell coercion/validation is left to the
service so it can report *why* a row was skipped rather than drop it silently.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import openpyxl
import xlrd

from src.core.exceptions import ValidationError

#: Header text (normalised) that identifies the join-key column.
_NM_ID_HEADERS = {"артикул wb", "nm_id", "nmid"}
#: Substring a cost header must contain to be the editable per-unit column.
_COST_MARKER = "себестоимость"


@dataclass(frozen=True)
class ParsedCostRow:
    """One data row lifted from an upload, still unvalidated.

    The cells are carried exactly as the reader returned them (``nm_id`` may be a
    float from Excel or text from CSV; a cost may be blank, a number, or a stray
    string) so the service can turn each kind of problem into a specific,
    row-numbered issue.
    """

    row: int
    nm_id_raw: object
    cost_raw: object


def parse_cost_upload(filename: str, data: bytes) -> list[ParsedCostRow]:
    """Parse an uploaded cost sheet, dispatching on its format.

    The format is taken from the file extension, falling back to the byte
    signature (a real ``.xlsx`` is a ZIP, a real ``.xls`` an OLE compound file),
    so a mislabelled but valid file still reads.

    Args:
        filename: The uploaded file's name (for the extension).
        data: Its raw bytes.

    Returns:
        The data rows, in sheet order.

    Raises:
        ValidationError: Unreadable bytes, an unsupported format, or a sheet with
            neither a key nor a cost column.
    """
    header, rows = _read_grid(filename, data)
    nm_col = _find_key_column(header)
    cost_col = _find_cost_column(header)
    if nm_col is None or cost_col is None:
        raise ValidationError(
            "Не найдены столбцы «Артикул WB» и «Себестоимость». "
            "Загрузите файл, скачанный из этого модуля."
        )
    parsed: list[ParsedCostRow] = []
    for offset, row in enumerate(rows, start=2):
        nm_raw = row[nm_col] if nm_col < len(row) else None
        if nm_raw is None or (isinstance(nm_raw, str) and nm_raw.strip() == ""):
            continue  # A blank line — every format pads the tail with these.
        cost_raw = row[cost_col] if cost_col < len(row) else None
        parsed.append(ParsedCostRow(row=offset, nm_id_raw=nm_raw, cost_raw=cost_raw))
    return parsed


def _read_grid(filename: str, data: bytes) -> tuple[list[object], list[list[object]]]:
    """Return ``(header_cells, data_rows)`` for a file of any supported format."""
    kind = _detect_format(filename, data)
    if kind == "xlsx":
        grid = _read_xlsx(data)
    elif kind == "xls":
        grid = _read_xls(data)
    else:
        grid = _read_csv(data)
    if not grid:
        raise ValidationError("Файл пуст — в нём нет строки заголовков.")
    return grid[0], grid[1:]


def _detect_format(filename: str, data: bytes) -> str:
    """Pick a reader from the byte signature first, then the extension.

    The signature wins because it cannot lie: a real ``.xlsx`` is a ZIP and a
    real ``.xls`` an OLE compound file, so a workbook saved under a ``.csv`` name
    (or with none) still reads. Only when the bytes are neither does the name
    decide, defaulting to CSV.
    """
    if data[:2] == b"PK":  # ZIP container → OOXML .xlsx
        return "xlsx"
    if data[:4] == b"\xd0\xcf\x11\xe0":  # OLE compound file → legacy .xls
        return "xls"
    name = filename.lower().strip()
    if name.endswith(".xls"):
        return "xls"
    return "csv"


def _read_xlsx(data: bytes) -> list[list[object]]:
    """Read an .xlsx workbook's active sheet into a list of rows."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of types on a bad file.
        raise ValidationError(_UNREADABLE) from exc
    try:
        ws = wb.active
        if ws is None:
            raise ValidationError("В файле нет ни одного листа.")
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _read_xls(data: bytes) -> list[list[object]]:
    """Read a legacy .xls workbook's first sheet into a list of rows."""
    try:
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
    except Exception as exc:
        raise ValidationError(_UNREADABLE) from exc
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def _read_csv(data: bytes) -> list[list[object]]:
    """Read a CSV/TSV into a list of rows, sniffing encoding and delimiter."""
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # A single column, or too little to sniff — comma is fine.
    return [list(row) for row in csv.reader(io.StringIO(text), dialect)]


def _decode(data: bytes) -> str:
    """Decode CSV bytes: UTF-8 (BOM-tolerant), then Windows-1251 for old exports."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError(_UNREADABLE)


def _find_key_column(header: list[object]) -> int | None:
    """Index of the «Артикул WB» / ``nm_id`` column, or ``None``."""
    for idx, cell in enumerate(header):
        if _norm(cell) in _NM_ID_HEADERS:
            return idx
    return None


def _find_cost_column(header: list[object]) -> int | None:
    """Index of the editable per-unit cost column, or ``None``.

    Prefers a «себестоимость … ед …» header (the export's «за 1 ед.»), so the
    total-cost column «Себестоимость, итого» beside it is never read by mistake.
    Falls back to any «себестоимость» header for a minimal hand-made sheet.
    """
    fallback: int | None = None
    for idx, cell in enumerate(header):
        text = _norm(cell)
        if _COST_MARKER in text:
            if "ед" in text:
                return idx
            if fallback is None:
                fallback = idx
    return fallback


def _norm(cell: object) -> str:
    """Normalise a header cell for comparison: trimmed, lower-cased, single-spaced."""
    if cell is None:
        return ""
    return " ".join(str(cell).strip().lower().split())


_UNREADABLE = (
    "Не удалось прочитать файл. Поддерживаются .xlsx, .xls и .csv — "
    "загрузите файл, скачанный из этого модуля."
)

__all__ = ["ParsedCostRow", "parse_cost_upload"]
