"""Read WB's weekly detailed report workbook into settlement rows.

The file is what the seller downloads from WB's seller portal: a zip holding one
.xlsx, one sheet, a header row and one row per settlement line. Every column is
located **by its header text**, and the set below was matched against the API's
rows of report 992915233 value by value — 3 257 rows, each column agreeing on
every row — except where noted:

* WB's reward net of VAT (``ppvz_vw``) is a full float in the file; the
  table keeps ten places, as the API's value does once stored.
* The order date and the sale date are Moscow dates; the API's are
  a day earlier on ~7 % of rows (an evening event read in UTC). Neither is a key.
* The columns that were zero on every row of that report — ``ppvz_reward``,
  ``additional_payment``, ``rebill_logistic_cost``, ``acceptance``, the
  loyalty and co-financing amounts, the promo percentages — are mapped by WB's
  documented names and not yet by value. The comparison with the API when it
  serves the report covers them: a wrong mapping there is a divergence alert.

What the file does not carry, and the caller supplies: the row's ``rrdId``, the
report number (it is in the file NAME), the settlement currency, and the
operation date ``rr_dt`` — derived here as the sale date clamped into the
period, which is the operation date on 3 179 of 3 257 rows and a day or two early
on the rest, all of them logistics.

Hostile input is assumed: the archive's declared sizes are checked before
anything is parsed, and the row cap holds while iterating.
"""

# check fires on ordinary Cyrillic. The headers were matched against WB's own file
# of report 992915233, every one of them.
from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import openpyxl

from src.core.exceptions import ValidationError

#: Rows one upload may hold. The largest week seen was 71 539; twice that is room.
MAX_ROWS = 150_000
#: Uncompressed bytes an archive may declare — about 3.7 KB of sheet XML a row.
MAX_DECOMPRESSED_BYTES = 640 * 1024 * 1024
#: Expansion an archive may claim. WB's own sheets compress about 7:1.
MAX_COMPRESSION_RATIO = 50

_NOT_A_REPORT = (
    "This isn't a WB detailed report. Upload the weekly detailed report "
    "exactly as downloaded from the WB seller portal."
)
_UNREADABLE = "Couldn't read the file. Upload the .zip or .xlsx from the WB seller portal."
_TOO_LARGE = "File too large for one weekly report."
_NO_NUMBER = (
    "No report number in the file name. Upload the file under the name "
    'the WB seller portal gave it: "…№123456789…".'
)

#: "№992915233" in WB's file name, "<report title> №992915233_9383646.zip".
_REPORT_NUMBER = re.compile(r"№\s*(\d{6,})")

_TEXT = {
    "Предмет": "subject_name",
    "Бренд": "brand_name",
    "Артикул поставщика": "sa_name",
    "Размер": "ts_name",
    "Баркод": "barcode",
    "Тип документа": "doc_type_name",
    "Обоснование для оплаты": "supplier_oper_name",
    "Виды логистики, штрафов и корректировок ВВ": "bonus_type_name",
    "Наименование банка-эквайера": "acquiring_bank",
    "Склад": "office_name",
    "Страна": "site_country",
    "Тип коробов": "gi_box_type_name",
    "Srid": "srid",
    "Тип платежа: компенсация платёжных услуг/Комиссия за интеграцию платёжных сервисов": (
        "payment_processing"
    ),
    "Способы продажи и тип товара": "delivery_method",
}
_INT = {
    "Код номенклатуры": "nm_id",
    "Кол-во": "quantity",
    "Количество доставок": "delivery_amount",
    "Количество возврата": "return_amount",
}
_GI_ID = "Номер поставки"
_SHK_ID = "ШК"
_DATE = {
    "Дата заказа покупателем": "order_dt",
    "Дата продажи": "sale_dt",
    "Дата начала действия фиксации": "fix_tariff_date_from",
    "Дата конца действия фиксации": "fix_tariff_date_to",
}
_MONEY = {
    "Цена розничная": "retail_price",
    "Вайлдберриз реализовал Товар (Пр)": "retail_amount",
    "Согласованный продуктовый дисконт, %": "product_discount_for_report",
    "Промокод, %": "supplier_promo",
    "Итоговая согласованная скидка, %": "sale_percent",
    "Цена розничная с учетом согласованной скидки": "retail_price_withdisc_rub",
    "Платформенные скидки, %": "ppvz_spp_prc",
    "Размер кВВ, %": "commission_percent",
    "Размер кВВ без НДС, % Базовый": "ppvz_kvw_prc_base",
    "Итоговый кВВ без НДС, %": "ppvz_kvw_prc",
    "Вознаграждение с продаж до вычета услуг поверенного, без НДС": "ppvz_sales_commission",
    "Возмещение за выдачу и возврат товаров на ПВЗ": "ppvz_reward",
    "Компенсация платёжных услуг/Комиссия за интеграцию платёжных сервисов": "acquiring_fee",
    "Размер компенсации платёжных услуг/Комиссии за интеграцию платёжных сервисов, %": (
        "acquiring_percent"
    ),
    "НДС с Вознаграждения Вайлдберриз": "ppvz_vw_nds",
    "К перечислению Продавцу за реализованный Товар": "ppvz_for_pay",
    "Услуги по доставке товара покупателю": "delivery_rub",
    "Общая сумма штрафов": "penalty",
    "Корректировка Вознаграждения Вайлдберриз (ВВ)": "additional_payment",
    "Возмещение издержек по перевозке/по складским операциям с товаром": ("rebill_logistic_cost"),
    "Хранение": "storage_fee",
    "Удержания": "deduction",
    "Услуга по обработке Товара": "acceptance",
    "Скидка по программе софинансирования": "installment_cofinancing_amount",
    "Компенсация скидки по программе лояльности": "cashback_discount",
    "Стоимость участия в программе лояльности": "cashback_commission_change",
    "Сумма баллов, удержанных по программе лояльности": "cashback_amount",
    "Размер дополнительной скидки по собственной акции продавца, %": "seller_promo_discount",
    "Размер скидки лояльности от продавца, %": "loyalty_discount",
    "Удержание Агентского НДС": "agency_vat",
}
_VW = "Вознаграждение Вайлдберриз (ВВ), без НДС"
_DLV_PRC = "Фиксированный коэффициент склада по поставке"
_SRV_DBS = "Признак услуги платной доставки"
_ORDINAL = "№"

REQUIRED_HEADERS: frozenset[str] = frozenset(
    {*_TEXT, *_INT, *_DATE, *_MONEY, _GI_ID, _SHK_ID, _VW, _DLV_PRC, _SRV_DBS, _ORDINAL}
)

#: Each header by the ``logistics_transaction`` column it fills, so code that
#: knows the column (a test building WB's file) need not spell WB's header.
HEADER_FOR: dict[str, str] = {
    column: header for header, column in (_TEXT | _INT | _DATE | _MONEY).items()
} | {"gi_id": _GI_ID, "shk_id": _SHK_ID, "ppvz_vw": _VW, "dlv_prc": _DLV_PRC, "srv_dbs": _SRV_DBS}


@dataclass(frozen=True, slots=True)
class OpenedReport:
    """A workbook that passed the cheap checks, not yet read row by row."""

    report_id: int
    xlsx: bytes


def report_number(*names: str) -> int | None:
    """WB's report number from the first of ``names`` that carries "№…"."""
    for name in names:
        match = _REPORT_NUMBER.search(name or "")
        if match:
            return int(match.group(1))
    return None


def open_upload(filename: str, data: bytes) -> OpenedReport:
    """Accept WB's zip or the .xlsx inside it; refuse anything else, cheaply.

    Nothing here parses a sheet: it bounds the archive, unwraps the zip and
    finds the report number, so the route can refuse a wrong file before
    anything is queued.

    Raises:
        ValidationError: Not a zip, a zip without exactly one workbook, an
            archive declaring an absurd size, or no report number in any name.
    """
    if data[:2] != b"PK":
        raise ValidationError(_UNREADABLE)
    names = [filename]
    archive = _bounded_zip(data)
    if "[Content_Types].xml" in archive.namelist():
        xlsx = data
    else:
        books = [n for n in archive.infolist() if n.filename.lower().endswith(".xlsx")]
        if len(books) != 1:
            raise ValidationError(_NOT_A_REPORT)
        names.append(_member_name(books[0]))
        xlsx = archive.read(books[0])
        _bounded_zip(xlsx)
    number = report_number(*names)
    if number is None:
        raise ValidationError(_NO_NUMBER)
    return OpenedReport(report_id=number, xlsx=xlsx)


def iter_report_rows(xlsx: bytes) -> Iterator[dict[str, Any]]:
    """Yield each data row as ``logistics_transaction`` columns, minus what the caller adds.

    The caller supplies ``rrd_id``, ``report_id``, ``workspace_id``,
    ``currency_name`` and ``rr_dt``. Streaming, so a 70 000-row week costs one
    row at a time; run it twice rather than holding it.

    Raises:
        ValidationError: Missing columns, a broken "№" sequence (an edited or
            cut file), an unreadable cell, or more than :data:`MAX_ROWS` rows.
    """
    try:
        book = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a zoo of types on a bad file.
        raise ValidationError(_UNREADABLE) from exc
    try:
        sheet = book.worksheets[0]
        # WB writes a one-cell <dimension>; trusted, it hides every row but the first.
        sheet.reset_dimensions()
        rows = sheet.iter_rows(values_only=True)
        header = [str(cell).strip() if cell is not None else "" for cell in next(rows, ())]
        missing = REQUIRED_HEADERS - set(header)
        if missing:
            raise ValidationError(_NOT_A_REPORT)
        at = {name: index for index, name in enumerate(header)}
        for ordinal, cells in enumerate(rows, start=1):
            if ordinal > MAX_ROWS:
                raise ValidationError(_TOO_LARGE)
            if all(cell is None or cell == "" for cell in cells):
                continue
            yield _row(cells, at, ordinal)
    finally:
        book.close()


def _row(cells: tuple[Any, ...], at: dict[str, int], ordinal: int) -> dict[str, Any]:
    """Map one sheet row; ``ordinal`` is where it must sit in WB's "№" sequence."""

    def cell(name: str) -> Any:
        index = at[name]
        return cells[index] if index < len(cells) else None

    if _int(cell(_ORDINAL), ordinal) != ordinal:
        raise ValidationError(
            "The report's rows are out of sequence: the file was edited or cut. "
            "Download it again from the WB seller portal."
        )
    row: dict[str, Any] = {column: _text(cell(name)) for name, column in _TEXT.items()}
    row |= {column: _int(cell(name), ordinal) for name, column in _INT.items()}
    # Blank in the file: no supply is NULL in the API's row, no barcode is 0.
    gi_id = cell(_GI_ID)
    row["gi_id"] = None if gi_id in (None, "") else _int(gi_id, ordinal)
    shk_id = cell(_SHK_ID)
    row["shk_id"] = 0 if shk_id in (None, "") else _int(shk_id, ordinal)
    row |= {column: _date(cell(name), ordinal) for name, column in _DATE.items()}
    row |= {column: _money(cell(name), ordinal) for name, column in _MONEY.items()}
    row["ppvz_vw"] = _money(cell(_VW), ordinal).quantize(Decimal("1e-10"))
    dlv = cell(_DLV_PRC)
    row["dlv_prc"] = None if dlv in (None, "") else _money(dlv, ordinal)
    row["srv_dbs"] = _text(cell(_SRV_DBS)).lower() in {"да", "true", "1"}
    return row


def _bounded_zip(data: bytes) -> zipfile.ZipFile:
    """Open an archive after checking what it declares it will expand to."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        declared = sum(entry.file_size for entry in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise ValidationError(_UNREADABLE) from exc
    if declared > MAX_DECOMPRESSED_BYTES or declared > MAX_COMPRESSION_RATIO * len(data):
        raise ValidationError(_TOO_LARGE)
    return archive


def _member_name(entry: zipfile.ZipInfo) -> str:
    """A member's name as its author wrote it — WB's zip omits the UTF-8 flag."""
    if entry.flag_bits & 0x800:
        return entry.filename
    try:
        return entry.filename.encode("cp437").decode("utf-8")
    except UnicodeError:
        return entry.filename


def _bad(ordinal: int) -> ValidationError:
    return ValidationError(f"Couldn't read row {ordinal} of the report.")


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _money(value: object, ordinal: int) -> Decimal:
    if value is None or value == "":
        return Decimal(0)
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise _bad(ordinal) from exc


def _int(value: object, ordinal: int) -> int:
    number = _money(value, ordinal)
    if number != number.to_integral_value():
        raise _bad(ordinal)
    return int(number)


def _date(value: object, ordinal: int) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise _bad(ordinal) from exc


__all__ = [
    "HEADER_FOR",
    "MAX_ROWS",
    "REQUIRED_HEADERS",
    "OpenedReport",
    "iter_report_rows",
    "open_upload",
    "report_number",
]
