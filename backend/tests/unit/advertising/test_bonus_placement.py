"""Placing WB's batched bonus charges on the days and parts they paid for."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.modules.advertising.services.bonus import place_bonus, split_by_weight

D1, D2, D3, D4 = (date(2026, 9, day) for day in (13, 14, 15, 16))


def test_a_charge_pays_for_its_own_day_first() -> None:
    """A charge no larger than its day's spend stays on that day."""
    placed = place_bonus({D1: Decimal("100"), D2: Decimal("100")}, {D2: Decimal("40")})

    assert placed == {D2: Decimal("40.00")}


def test_an_evening_batch_spills_onto_the_days_already_served_before_later_ones() -> None:
    """A 22:45 batch pays for impressions already shown — earlier days take the overflow first."""
    spend = {D1: Decimal("100"), D2: Decimal("100"), D3: Decimal("100"), D4: Decimal("100")}

    placed = place_bonus(spend, {D3: Decimal("250")})

    assert placed == {D3: Decimal("100.00"), D2: Decimal("100.00"), D1: Decimal("50.00")}


def test_the_bonus_never_exceeds_the_spend_it_paid_for() -> None:
    """No day's advertising may go negative; only the surplus over the whole spend is dropped."""
    placed = place_bonus({D1: Decimal("30"), D2: Decimal("20")}, {D2: Decimal("500")})

    assert sum(placed.values()) == Decimal("50")
    assert placed == {D2: Decimal("20.00"), D1: Decimal("30.00")}


def test_a_charge_dated_outside_the_spend_still_finds_the_campaigns_days() -> None:
    """A charge on a day the campaign served nothing is placed on its nearest earlier days."""
    placed = place_bonus({D1: Decimal("60"), D2: Decimal("60")}, {D4: Decimal("70")})

    assert placed == {D2: Decimal("60.00"), D1: Decimal("10.00")}


def test_a_split_always_sums_to_the_whole_to_the_kopeck() -> None:
    """Thirds of a kopeck-odd amount still add back up: the heaviest part takes the remainder."""
    weights = {"a": Decimal("1"), "b": Decimal("1"), "c": Decimal("1.01")}

    parts = split_by_weight(Decimal("100.00"), weights)

    assert sum(parts.values()) == Decimal("100.00")
    assert parts == {"a": Decimal("33.22"), "b": Decimal("33.22"), "c": Decimal("33.56")}
