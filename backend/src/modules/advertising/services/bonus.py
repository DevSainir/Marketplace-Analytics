"""Putting WB's bonus on the days, zones and articles it paid for.

WB's ledger says how much of a CAMPAIGN's advertising its bonus pool paid, on
the day it charged it — in batches, one row at 22:45 covering a day or more of
impressions. The page shows that money per day, per zone and per article, so it
has to be placed; these two functions are the whole model, and they keep every
cut summing to the same total.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from datetime import date
from decimal import Decimal

_ZERO = Decimal(0)
_CENT = Decimal("0.01")


def place_bonus(
    spend_by_day: Mapping[date, Decimal], charged_by_day: Mapping[date, Decimal]
) -> dict[date, Decimal]:
    """Place one campaign's charged bonus on the days it ran, never above a day's spend.

    Each charge first covers its own day. What a day cannot hold goes to the
    days BEFORE it, newest first — a batch charged in the evening pays for
    impressions already served — and only then to the days after. So the bonus
    shows up where it was actually spent (on «Демо» that is 13-25.09.2026,
    not smeared over a month), no day's advertising goes negative, and the
    placed total is exactly ``min(Σ charged, Σ spend)``: a charge whose
    impressions fell outside the window is the only thing ever dropped.

    Returns:
        ``{day: bonus}`` for the days that received any; quantized to kopecks.
    """
    days = sorted(spend_by_day)
    room = {day: spend_by_day[day] for day in days}
    placed: dict[date, Decimal] = {}

    def take(day: date, amount: Decimal) -> Decimal:
        portion = min(amount, room[day])
        if portion > 0:
            room[day] -= portion
            placed[day] = placed.get(day, _ZERO) + portion
            return amount - portion
        return amount

    for charge_day in sorted(charged_by_day):
        left = charged_by_day[charge_day]
        if left <= 0:
            continue
        if charge_day in room:
            left = take(charge_day, left)
        for day in reversed([d for d in days if d < charge_day]):
            if left <= 0:
                break
            left = take(day, left)
        for day in [d for d in days if d > charge_day]:
            if left <= 0:
                break
            left = take(day, left)
    return {day: amount.quantize(_CENT) for day, amount in placed.items() if amount}


def split_by_weight[K: Hashable](amount: Decimal, weights: Mapping[K, Decimal]) -> dict[K, Decimal]:
    """Split ``amount`` across keys in proportion to their weights, to the kopeck.

    The heaviest key takes the rounding remainder, so the parts always sum to
    ``amount`` exactly — the property that keeps the zone table, the article
    table and the headline card on one total.
    """
    positive = {key: weight for key, weight in weights.items() if weight > 0}
    total = sum(positive.values(), _ZERO)
    if not positive or not amount:
        return {}
    heaviest = max(positive, key=lambda key: positive[key])
    parts = {
        key: (amount * weight / total).quantize(_CENT)
        for key, weight in positive.items()
        if key != heaviest
    }
    parts[heaviest] = amount - sum(parts.values(), _ZERO)
    return {key: part for key, part in parts.items() if part}
