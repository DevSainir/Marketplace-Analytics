"""Which currency each money cell is in, and which cells may be computed at all.

A кабинет that settles in KGS was billed for ads in RUB until 20.08.2026 and
in KGS after; its order money is WB's funnel sum in KGS. Rouble spend is
converted where it is stored, at the Bank of Russia rate of its day — WB's own
rule — so normally every cell is in one currency (``repos/ad_money.py``,
wildberries-api/references/currencies.md).

What is left here is the guard for a row the conversion could not reach — a
rouble day past the loaded rates: a figure that would add or divide two
currencies is «—» rather than a number off by the day's exchange rate.
"""

from __future__ import annotations

from src.modules.monitoring.schemas.matrix import (
    MatrixAdBucketBase,
    MatrixDayBase,
    MatrixDayCurrencies,
)
from src.modules.monitoring.services.matrix.pricing import order_unit


def card_ad_currencies(day: MatrixDayBase) -> list[str]:
    """The currencies of the card's whole advertising day («Общая»)."""
    codes: set[str] = set()
    for bucket in (*day.buckets.values(), day.unclassified):
        codes.update(bucket.currencies)
    return sorted(codes)


def spend_is_mixed(codes: list[str]) -> bool:
    """Whether a spend sum adds money of two currencies — then it is not shown.

    Only STATED codes count: a campaign harvested before WB's label was
    recorded (``""``) is one campaign, not a second currency.
    """
    return len({code for code in codes if code}) > 1


def pairs_with_orders(codes: list[str], day: MatrixDayBase) -> bool:
    """Whether spend in ``codes`` may be divided by the day's order money (ДРР).

    Only when both are one stated currency — a rouble row the conversion could
    not reach would divide roubles by сомы.
    """
    _price, orders = order_unit(day.funnel)
    return bool(orders) and codes == [orders]


def day_currencies(day: MatrixDayBase) -> MatrixDayCurrencies:
    """What the money cells of one day column are counted in."""
    ads: dict[str, list[str]] = {
        name: list(bucket.currencies) for name, bucket in day.buckets.items()
    }
    ads["total"] = card_ad_currencies(day)
    return MatrixDayCurrencies(orders=order_unit(day.funnel)[1], ads=ads)


def bucket_codes(bucket: MatrixAdBucketBase | None) -> list[str]:
    """A bucket's spend currencies (none for a bucket that did not deliver)."""
    return [] if bucket is None else list(bucket.currencies)
