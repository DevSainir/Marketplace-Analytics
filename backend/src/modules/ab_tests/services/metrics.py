"""Variant totals and the three funnel ratios the result table shows.

Ratios are derived here, never stored, for the reason "Buyout rate" is
derived in the monitoring module: a percentage cannot be re-aggregated. Averaging
a variant's daily CTRs weights a 100-impression day the same as a 10 000-one and
answers a question nobody asked, so totals are summed first and divided once.

The three ratios are **chained**, each dividing by the previous stage — the same
definition WB's own A/B result screen uses:

    click-through (share of views that click into the card) = clicks / views
    add-to-cart   (share of clicks that add to the cart)    = atbs   / clicks
    order rate    (share of carts that become orders)       = orders / atbs
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

#: Percentages are reported to two decimals, matching WB's own presentation.
_PERCENT = Decimal("0.01")


class HasCounts(Protocol):
    """Anything carrying one interval's counts — a stored row or a fake."""

    @property
    def views(self) -> int: ...

    @property
    def clicks(self) -> int: ...

    @property
    def atbs(self) -> int: ...

    @property
    def orders(self) -> int: ...

    @property
    def spend(self) -> Decimal: ...


@dataclass(frozen=True)
class WindowCounts:
    """One polling interval's traffic for one variant.

    The grain used to be a calendar day, because the numbers came from a
    once-a-day harvest. It is now a poll, so a photo can turn over several times
    a day and still be measured on intervals it owned outright.
    """

    window_end: datetime
    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass(frozen=True)
class VariantTotals:
    """A variant's counts summed over every day it was live."""

    views: int = 0
    clicks: int = 0
    atbs: int = 0
    orders: int = 0
    spend: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass(frozen=True)
class VariantConversions:
    """The three chained ratios, in percent.

    ``None`` means the stage's denominator was empty — nobody got that far yet.
    It is deliberately not ``0``: zero reads as "converted nobody" and would pull
    a comparison down, while the honest answer is that there is no measurement.
    """

    click_through: Decimal | None
    add_to_cart: Decimal | None
    order_rate: Decimal | None


def totals_from_windows(windows: Iterable[HasCounts]) -> VariantTotals:
    """Sum a variant's polling intervals into one total.

    Args:
        windows: The variant's recorded intervals, in any order.

    Returns:
        The summed counts; all zeroes when there are none.
    """
    views = clicks = atbs = orders = 0
    spend = Decimal("0")
    for window in windows:
        views += window.views
        clicks += window.clicks
        atbs += window.atbs
        orders += window.orders
        spend += Decimal(window.spend)
    return VariantTotals(views=views, clicks=clicks, atbs=atbs, orders=orders, spend=spend)


def _percent(numerator: int, denominator: int) -> Decimal | None:
    """Return ``numerator / denominator`` as a 2-decimal percent, or ``None``.

    Args:
        numerator: Events that reached the later stage.
        denominator: Events that reached the earlier stage.

    Returns:
        The percentage rounded half-up to two decimals, or ``None`` when the
        denominator is zero.
    """
    if denominator <= 0:
        return None
    ratio = (Decimal(numerator) / Decimal(denominator)) * Decimal(100)
    return ratio.quantize(_PERCENT, rounding=ROUND_HALF_UP)


def conversions(totals: VariantTotals) -> VariantConversions:
    """Derive the three funnel ratios from a variant's totals.

    Args:
        totals: Summed counts for the variant.

    Returns:
        The chained percentages, each ``None`` where its denominator is empty.
    """
    return VariantConversions(
        click_through=_percent(totals.clicks, totals.views),
        add_to_cart=_percent(totals.atbs, totals.clicks),
        order_rate=_percent(totals.orders, totals.atbs),
    )
