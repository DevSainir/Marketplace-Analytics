"""XLSX export of the per-SKU P&L, with an editable cost column.

The seller's cost of goods is the one P&L input WB cannot supply, and typing it
SKU-by-SKU does not scale. Sellers keep these figures in spreadsheets already,
so the export is the whole "By SKU" statement — every column the on-screen
table shows — with one column left for the seller to fill: **"Cost price per
unit"**. They edit it offline and upload the same file back, where only that
column (matched to a SKU by **"WB ID"** = ``nm_id``) is read.

Written with ``xlsxwriter``; the formatting the one sheet needs (a header fill
and a money format) is set up locally. Reading the file back is a separate
concern and lives in :mod:`.cost_upload_parser` (a different library on
purpose, so a bug shared by writer and reader cannot hide a broken column).

The two identity columns are deliberate and named to match the UI:

* **"WB ID"** carries ``nm_id`` — the *only* stable key. The importer joins
  on it, never on the seller's article, because one vendor code can span
  several WB cards and a cost applied to the wrong one is a plausible, silent
  error (PNL.md §13).
* **"Vendor code"** carries the seller's own ``sa_name``, for the human reading the
  sheet.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from decimal import Decimal

import xlsxwriter

from src.modules.finreports.schemas.sku_report import PnlSkuReportResponse, PnlSkuRow

SHEET_TITLE = "P&L by SKU"

#: Header fill — a deep blue.
_HEADER_BG = "#1F3864"

#: The editable column's exact header. The parser matches "cost price" + "unit",
#: so this survives a rename to e.g. "Cost price per unit, KGS".
COST_HEADER = "Cost price per unit"
#: The identity column the importer joins on (its values are ``nm_id``).
NM_ID_HEADER = "WB ID"


def _money(value: Decimal | None) -> float | None:
    """Excel wants a float; ``None`` stays a blank cell, never a 0."""
    return float(value) if value is not None else None


# Column spec: (header, width, kind, getter). ``kind`` drives the number format.
# Order mirrors the on-screen "By SKU" table; the editable cost sits with
# the other margin inputs, its total (COGS) beside it.
_COLUMNS: list[tuple[str, int, str, Callable[[PnlSkuRow], object]]] = [
    ("Vendor code", 22, "text", lambda r: r.sa_name),
    (NM_ID_HEADER, 14, "int", lambda r: r.nm_id),
    ("Category", 20, "text", lambda r: r.subject_name),
    ("Brand", 18, "text", lambda r: r.brand_name),
    ("Orders, units", 12, "int", lambda r: r.orders_units),
    ("Sales, units", 12, "int", lambda r: r.sold_units),
    ("Returns, units", 12, "int", lambda r: r.returned_units),
    ("Returns, %", 12, "pct", lambda r: _money(r.return_rate_pct)),
    ("Buyout rate, %", 12, "pct", lambda r: _money(r.buyout_pct)),
    ("Sales", 16, "money", lambda r: _money(r.revenue_paid)),
    ("Average receipt", 14, "money", lambda r: _money(r.average_cheque)),
    ("WB discount, %", 10, "pct", lambda r: _money(r.spp_pct)),
    ("Logistics", 14, "money", lambda r: _money(r.logistics_total)),
    ("Penalties", 12, "money", lambda r: _money(r.penalties_total)),
    (COST_HEADER, 20, "money", lambda r: _money(r.cost_price)),
    ("Cost price, total", 20, "money", lambda r: _money(r.cogs)),
    ("Advertising", 14, "money", lambda r: _money(r.advertising)),
    # Negative on purpose: the sheet shows it the way the screen does, as a
    # deduction from the column on its left. The model stores the magnitude.
    ("Bonuses", 14, "money", lambda r: _money(-r.ad_bonus) if r.ad_bonus else _money(r.ad_bonus)),
    ("Payout", 16, "money", lambda r: _money(r.payout_net)),
    ("Net profit", 16, "money", lambda r: _money(r.net_profit)),
    ("Profit, %", 12, "pct", lambda r: _money(r.net_profit_pct)),
    ("ROI, %", 10, "pct", lambda r: _money(r.roi_pct)),
]


def build_pnl_workbook(report: PnlSkuReportResponse) -> bytes:
    """Render the per-SKU P&L into a single-sheet XLSX for offline cost entry.

    Lays out every SKU row largest-revenue-first (as the report already orders
    them), then the account-level "Not tied to a SKU" bucket and the
    reconciled "TOTAL" — the same Σ rows + unallocated = totals frame the screen
    shows, so a seller can check the sheet foots.

    Args:
        report: The per-SKU P&L report for the export window.

    Returns:
        The workbook as bytes, ready to stream from the download route.
    """
    buffer = io.BytesIO()
    wb = xlsxwriter.Workbook(buffer, {"in_memory": True})
    fmt = {
        "header": wb.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": _HEADER_BG,
                "border": 1,
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "money": wb.add_format({"num_format": "#,##0.00"}),
        "pct": wb.add_format({"num_format": "0.00"}),
        "total": wb.add_format({"bold": True}),
        "total_money": wb.add_format({"bold": True, "num_format": "#,##0.00"}),
        "total_pct": wb.add_format({"bold": True, "num_format": "0.00"}),
    }

    ws = wb.add_worksheet(SHEET_TITLE)
    ws.freeze_panes(1, 0)
    for col, (title, width, _kind, _get) in enumerate(_COLUMNS):
        ws.set_column(col, col, width)
        ws.write(0, col, title, fmt["header"])

    r = 1
    for row in report.rows:
        _write_row(ws, r, row, fmt, bold=False)
        r += 1
    if report.unallocated is not None:
        bucket = report.unallocated.model_copy(update={"sa_name": "Not tied to a SKU"})
        _write_row(ws, r, bucket, fmt, bold=True)
        r += 1
    totals = report.totals.model_copy(update={"sa_name": "TOTAL"})
    _write_row(ws, r, totals, fmt, bold=True)

    wb.close()
    return buffer.getvalue()


def _write_row(ws: object, r: int, row: PnlSkuRow, fmt: dict[str, object], *, bold: bool) -> None:
    """Write one data row, each cell formatted by its column kind.

    The summary rows (bucket, "TOTAL") get a blank "WB ID": they carry
    ``nm_id`` 0, and a re-import must skip them, not report them as unknown SKUs.
    An empty key cell is exactly the signal the parser drops on.
    """
    for col, (title, _width, kind, get) in enumerate(_COLUMNS):
        cell_fmt = _cell_format(kind, fmt, bold=bold)
        value = None if (bold and title == NM_ID_HEADER) else get(row)
        if value is None:
            ws.write_blank(r, col, None, cell_fmt)  # type: ignore[attr-defined]
        else:
            ws.write(r, col, value, cell_fmt)  # type: ignore[attr-defined]


def _cell_format(kind: str, fmt: dict[str, object], *, bold: bool) -> object:
    """Pick the cell format for a column kind, bolding the total/bucket rows."""
    if kind == "money":
        return fmt["total_money"] if bold else fmt["money"]
    if kind == "pct":
        return fmt["total_pct"] if bold else fmt["pct"]
    return fmt["total"] if bold else None


__all__ = ["COST_HEADER", "NM_ID_HEADER", "SHEET_TITLE", "build_pnl_workbook"]
