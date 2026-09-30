"""Which currency each money cell is in, and which cells may be computed at all.

A кабинет that settles in KGS holds money in two currencies at once: spend is
billed in what each campaign was created in (RUB before 20.08.2026, KGS after),
and the order money is WB's funnel sum in KGS. We never convert between them
(see wildberries-api/references/currencies.md), so a figure that would add or
divide the two is not shown — «—» instead of a number that looks right and is
off by the day's exchange rate.

# CONVERSION-TODO: every «—» decided here stands in for a number that needs a
# rate. When the service starts converting at the Bank of Russia rate, these are
# the places to turn into real figures: `spend_is_mixed` (a sum over campaigns
# billed in different currencies) and `pairs_with_orders` (ДРР whose spend and
# order money are in different currencies — every day before 20.08.2026).
# `grep -rn CONVERSION-TODO` lists every other site.
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
    # CONVERSION-TODO: a mixed sum becomes a real figure once one side is
    # converted into the other.
    return len({code for code in codes if code}) > 1


def pairs_with_orders(codes: list[str], day: MatrixDayBase) -> bool:
    """Whether spend in ``codes`` may be divided by the day's order money (ДРР).

    Only when both are one stated currency. On «Демо» that is every KGS
    campaign after 20.08.2026 against WB's KGS funnel sums; a RUB campaign
    before it would divide roubles by сомы.
    """
    # CONVERSION-TODO: ДРР of a RUB campaign (every day before 20.08.2026) is
    # «—» until the spend or the order money is converted.
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
