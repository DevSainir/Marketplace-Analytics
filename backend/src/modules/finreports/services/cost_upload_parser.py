"""Read an uploaded cost sheet back into per-row cells, in any of three formats.

The export hands out one shape (``build_pnl_workbook``); a seller may upload it
back as **.xlsx**, the legacy **.xls**, or a **.csv** exported from Excel or 1C.
Each reader is a different library, but all three converge on the same job: find
the two columns that matter and return every data row.

Only two columns are trusted, located **by header name** so the seller may
reorder, delete, or annotate the rest and the upload still lands:

* **"WB ID"** (or a bare ``nm_id``) — the join key. Nothing else identifies
  a SKU safely (PNL.md §13).
* **"Cost price per unit"** — the one figure read back. Matched loosely
  (contains "cost price" and "unit"), with a plain "Cost price" as a
  fallback for a minimal hand-made sheet.

What the parser will not do is guess: a file with no recognisable key or cost
header is rejected outright, and per-cell coercion/validation is left to the
service so it can report *why* a row was skipped rather than drop it silently.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass

import openpyxl
import xlrd

from src.core.exceptions import ValidationError
from src.core.logging import get_logger

logger = get_logger(__name__)

#: Header text (normalised) that identifies the join-key column.
_NM_ID_HEADERS = {"wb id", "nm_id", "nmid"}
#: Substring a cost header must contain to be the editable per-unit column.
_COST_MARKER = "cost price"
#: Substring that tells the per-unit cost column from the total beside it.
_PER_UNIT_MARKER = "unit"

#: Most data rows any upload may contain. This is the bound that actually holds:
#: the readers below stop **while iterating**, so a sheet that merely declares a
#: million rows costs the rows we read and not the rows it claims.
#:
#: 50 000 is far past any real catalogue (WB's own listings cap well below it)
#: while keeping the parsed list to something a 512 MB container can hold.
_MAX_ROWS = 50_000

#: Ceiling on an .xlsx's total *uncompressed* size, and on how far it may
#: expand. ``.xlsx`` is a ZIP, so a 10 MB upload can carry gigabytes of sheet
#: XML — the file-size check on the route bounds the compressed bytes and
#: therefore bounds nothing about what parsing them costs.
#:
#: Read as an early, cheap rejection rather than as the guarantee: these figures
#: come from the archive's own headers, which an adversary writes. The honest
#: bound is :data:`_MAX_ROWS` above, enforced against rows actually produced.
_MAX_DECOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200


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
            'No "WB ID" and "Cost price per unit" columns. '
            "Upload the file downloaded from this page."
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
        raise ValidationError("The file is empty: it has no header row.")
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
    """Read an .xlsx workbook's active sheet into a list of rows.

    ``read_only=True`` matters here beyond speed: it makes ``iter_rows`` stream
    the sheet, so the row cap below stops a hostile workbook part-way instead of
    after openpyxl has built every row in memory.
    """
    _reject_expansion_bomb(data)
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ValidationError:
        raise
    except Exception as exc:  # openpyxl raises a zoo of types on a bad file.
        raise ValidationError(_UNREADABLE) from exc
    try:
        ws = wb.active
        if ws is None:
            raise ValidationError("The file has no sheets.")
        rows: list[list[object]] = []
        for row in ws.iter_rows(values_only=True):
            if len(rows) >= _MAX_ROWS:
                raise ValidationError(_TOO_MANY_ROWS)
            rows.append(list(row))
        return rows
    finally:
        wb.close()


def _reject_expansion_bomb(data: bytes) -> None:
    """Refuse an .xlsx whose archive promises an absurd amount of sheet XML.

    Args:
        data: The uploaded bytes, already known to start with a ZIP signature.

    Raises:
        ValidationError: When the archive is unreadable, or declares more
            uncompressed bytes than :data:`_MAX_DECOMPRESSED_BYTES` or a
            greater expansion than :data:`_MAX_COMPRESSION_RATIO`.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            declared = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise ValidationError(_UNREADABLE) from exc
    ratio = declared / len(data) if data else 0
    if declared > _MAX_DECOMPRESSED_BYTES or ratio > _MAX_COMPRESSION_RATIO:
        logger.warning(
            "Refusing a cost upload: %d compressed bytes declaring %d uncompressed (%.0fx).",
            len(data),
            declared,
            ratio,
        )
        raise ValidationError(_TOO_LARGE_UNPACKED)


def _read_xls(data: bytes) -> list[list[object]]:
    """Read a legacy .xls workbook's first sheet into a list of rows."""
    try:
        book = xlrd.open_workbook(file_contents=data)
        sheet = book.sheet_by_index(0)
    except Exception as exc:
        raise ValidationError(_UNREADABLE) from exc
    if sheet.nrows > _MAX_ROWS:
        raise ValidationError(_TOO_MANY_ROWS)
    return [sheet.row_values(i) for i in range(sheet.nrows)]


def _read_csv(data: bytes) -> list[list[object]]:
    """Read a CSV/TSV into a list of rows, sniffing encoding and delimiter."""
    text = _decode(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # A single column, or too little to sniff — comma is fine.
    rows: list[list[object]] = []
    for row in csv.reader(io.StringIO(text), dialect):
        if len(rows) >= _MAX_ROWS:
            raise ValidationError(_TOO_MANY_ROWS)
        rows.append(list(row))
    return rows


def _decode(data: bytes) -> str:
    """Decode CSV bytes: UTF-8 (BOM-tolerant), then Windows-1251 for old exports."""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationError(_UNREADABLE)


def _find_key_column(header: list[object]) -> int | None:
    """Index of the "WB ID" / ``nm_id`` column, or ``None``."""
    for idx, cell in enumerate(header):
        if _norm(cell) in _NM_ID_HEADERS:
            return idx
    return None


def _find_cost_column(header: list[object]) -> int | None:
    """Index of the editable per-unit cost column, or ``None``.

    Prefers a "cost price … unit" header (the export's "per unit"), so the
    total-cost column "Cost price, total" beside it is never read by mistake.
    Falls back to any "cost price" header for a minimal hand-made sheet.
    """
    fallback: int | None = None
    for idx, cell in enumerate(header):
        text = _norm(cell)
        if _COST_MARKER in text:
            if _PER_UNIT_MARKER in text:
                return idx
            if fallback is None:
                fallback = idx
    return fallback


def _norm(cell: object) -> str:
    """Normalise a header cell for comparison: trimmed, lower-cased, single-spaced."""
    if cell is None:
        return ""
    return " ".join(str(cell).strip().lower().split())


_TOO_MANY_ROWS = (
    f"The file has more than {_MAX_ROWS:,} rows, so it isn't a cost price file. "
    "Upload the file downloaded from this page."
)

_TOO_LARGE_UNPACKED = "The file unpacks to an implausibly large amount of data and won't be read."

_UNREADABLE = (
    "Couldn't read the file. Supported formats are .xlsx, .xls and .csv: "
    "upload the file downloaded from this page."
)

__all__ = ["ParsedCostRow", "parse_cost_upload"]
