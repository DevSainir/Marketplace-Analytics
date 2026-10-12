"""What the seller is told about an upload — short, and in their words."""

# ruff: noqa: RUF001, RUF002 — the messages are Russian, and the confusable-character
# check fires on ordinary Cyrillic.
from __future__ import annotations

from datetime import date

_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def period_ru(date_from: date, date_to: date) -> str:
    """«5–11 окт», or «28 сен – 4 окт» across a month — WB's own shape."""
    if date_from.month == date_to.month:
        return f"{date_from.day}–{date_to.day} {_MONTHS[date_to.month - 1]}"
    return (
        f"{date_from.day} {_MONTHS[date_from.month - 1]} – "
        f"{date_to.day} {_MONTHS[date_to.month - 1]}"
    )


def rows_ru(count: int) -> str:
    """«3 257 строк», «1 строка», «2 строки»."""
    tens, ones = count % 100, count % 10
    if ones == 1 and tens != 11:
        word = "строка"
    elif 2 <= ones <= 4 and not 12 <= tens <= 14:
        word = "строки"
    else:
        word = "строк"
    return f"{count:,}".replace(",", " ") + f" {word}"


def written(date_from: date, date_to: date, *, total: int, added: int) -> str:
    """The rows now stand in the P&L — all of the file, or the ones we lacked."""
    period = period_ru(date_from, date_to)
    if added == total:
        return (
            f"Отчёт за {period} загружен — {rows_ru(total)}. Сверим с WB, когда он придёт по API."
        )
    return (
        f"Отчёт за {period} загружен: добавили {rows_ru(added)}, "
        f"остальные у нас уже были. Сверим с WB, когда он придёт по API."
    )


ALREADY_HELD = "Этот отчёт у нас уже есть — совпадает с файлом до строки."
DIVERGED = "Этот отчёт у нас уже есть, но отличается от файла. Мы проверим расхождение."
EMPTY = "В отчёте нет ни одной строки."
NO_CURRENCY = "Сначала дождитесь первого отчёта из WB — по нему узнаем валюту расчётов."
FAILED = "Не удалось обработать файл. Попробуйте загрузить его ещё раз."


def not_over(date_from: date, date_to: date) -> str:
    """The week is still running, so WB has no report for it yet."""
    return f"Неделя {period_ru(date_from, date_to)} ещё не закончилась — отчёта за неё пока нет."


__all__ = [
    "ALREADY_HELD",
    "DIVERGED",
    "EMPTY",
    "FAILED",
    "NO_CURRENCY",
    "not_over",
    "period_ru",
    "rows_ru",
    "written",
]
