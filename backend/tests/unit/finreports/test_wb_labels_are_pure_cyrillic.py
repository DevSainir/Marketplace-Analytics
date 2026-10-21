"""Every WB-served label we match on must be script-pure Cyrillic.

These constants are compared for **exact equality** against strings WildBerries
puts on settlement rows. A single Latin lookalike inside one of them — `Продажa`
with a Latin `a`, `Хранение` with a Latin `e` — matches nothing, raises nothing,
and silently removes a whole operation from the statement: the sale rows stop
being counted as units and revenue, and the P&L still balances because the
charge lines sum whole columns regardless.

Ruff's RUF001-003 used to be the net for this, but the root config has to
whitelist the Latin-lookalike Cyrillic letters that ordinary Russian prose in
docstrings is made of. This test replaces that protection with a stronger one: it
does not ask whether a character is *flagged*, it asks whether the string is
entirely Cyrillic-or-punctuation, which is the property that actually matters.
"""

from __future__ import annotations

import unicodedata

import pytest

from src.modules.finreports.constants import (
    ADVERTISING_DEDUCTION_MARKER,
    CLASSIFIED_OPERS,
    LOGISTICS_OPER,
    PENALTY_OPER,
    SEPARATELY_BILLED_ACQUIRING,
    SUBSCRIPTION_DEDUCTION_MARKER,
    TRANSIT_DEDUCTION_MARKER,
)
from src.modules.monitoring.models import BONUS_PAYMENT_TYPES, CASH_PAYMENT_TYPES

#: Non-letter characters a WB label may legitimately contain.
_ALLOWED_NON_LETTERS = set(" .,()/«»№-–—0123456789")


def _latin_letters(value: str) -> set[str]:
    """Return the Latin letters in a string that should carry none."""
    return {char for char in value if char.isalpha() and "LATIN" in unicodedata.name(char, "")}


def _unexpected(value: str) -> set[str]:
    """Return characters that are neither Cyrillic nor allowed punctuation."""
    return {char for char in value if not char.isalpha() and char not in _ALLOWED_NON_LETTERS}


@pytest.mark.parametrize("label", sorted(CLASSIFIED_OPERS))
def test_an_operation_name_contains_no_latin_lookalikes(label: str) -> None:
    """A ``supplier_oper_name`` we classify on is pure Cyrillic.

    One Latin character here drops the whole operation from the units and payout
    split while leaving the statement's totals looking plausible.
    """
    assert _latin_letters(label) == set()
    assert _unexpected(label) == set()


@pytest.mark.parametrize(
    "label",
    [
        LOGISTICS_OPER,
        PENALTY_OPER,
        ADVERTISING_DEDUCTION_MARKER,
        SUBSCRIPTION_DEDUCTION_MARKER,
        TRANSIT_DEDUCTION_MARKER,
        SEPARATELY_BILLED_ACQUIRING,
    ],
)
def test_a_reason_label_contains_no_latin_lookalikes(label: str) -> None:
    """The ``bonus_type_name``/``payment_processing`` markers are pure Cyrillic too.

    ``SEPARATELY_BILLED_ACQUIRING`` is the sharpest case: a mismatch there moves
    the whole acquiring fee between the acquiring and commission lines without
    changing any total, so nothing downstream would look wrong.
    """
    assert _latin_letters(label) == set()
    assert _unexpected(label) == set()


def test_the_taxonomy_covers_every_operation_the_statement_names() -> None:
    """The individually-named operations are all inside the classified set.

    Guards the split-brain where a constant is used by one layer and absent from
    the classifier the caveat check runs against.
    """
    assert {LOGISTICS_OPER, PENALTY_OPER} <= CLASSIFIED_OPERS


@pytest.mark.parametrize("label", sorted(BONUS_PAYMENT_TYPES | CASH_PAYMENT_TYPES))
def test_an_advertising_funding_label_contains_no_latin_lookalikes(label: str) -> None:
    """The ``paymentType`` allowlist is matched for exact equality too.

    A Latin lookalike in «Кэшбэк» is the quietest failure of the set: the label
    matches nothing, the bonus is silently treated as the seller's own money,
    and the report goes back to the inflated DRR it had before — with every
    total still reconciling, because the ledger never enters the settlement.
    """
    assert _latin_letters(label) == set()
    assert _unexpected(label) == set()


def test_no_label_is_both_a_bonus_and_the_sellers_own_money() -> None:
    """The two sets decide opposite things; an overlap makes one of them a lie."""
    assert set() == BONUS_PAYMENT_TYPES & CASH_PAYMENT_TYPES
