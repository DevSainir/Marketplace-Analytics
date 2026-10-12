"""Are two sets of settlement rows the same rows — the upload's and ours?

There is no shared row id to join on: the file has none and ours is WB's
``rrdId``. So a row is identified by what it says — operation, document, srid,
article, barcode, counts and every money column — and two sets are compared as
**multisets** of that. A row WB issues twice is two rows here too.

Dates are deliberately not in the key. The file's dates are Moscow days and the
API's are a day earlier on ~7 % of rows, and ``rr_dt`` is not in the file at all.
What a date would add the money columns already pin: on report 992915233 this
key matched 3 257 rows to 3 257, one to one.

Each key is held as a 16-byte hash, so the whole of NEVA's largest week (71 539
rows) is a few megabytes rather than the rows themselves.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.modules.finreports.constants import REFUND_DOC_TYPE

_TEXT_KEY = (
    "supplier_oper_name",
    "doc_type_name",
    "srid",
    "barcode",
    "bonus_type_name",
)
_INT_KEY = ("nm_id", "quantity", "delivery_amount", "return_amount")
_MONEY_KEY = (
    "retail_amount",
    "ppvz_for_pay",
    "delivery_rub",
    "penalty",
    "storage_fee",
    "deduction",
    "acquiring_fee",
    "ppvz_vw_nds",
    "ppvz_sales_commission",
    "ppvz_reward",
    "agency_vat",
    "additional_payment",
    "rebill_logistic_cost",
    "acceptance",
    "cashback_amount",
    "cashback_discount",
    "cashback_commission_change",
    "installment_cofinancing_amount",
)
#: Every column a row is identified by — what the comparison reads from the DB.
KEY_COLUMNS: tuple[str, ...] = (*_TEXT_KEY, *_INT_KEY, *_MONEY_KEY)

_CENT = Decimal("0.01")


def row_key(row: Mapping[str, Any]) -> bytes:
    """A row's identity as a 16-byte hash of its key columns."""
    parts = [str(row.get(column) or "") for column in _TEXT_KEY]
    parts += [str(int(row.get(column) or 0)) for column in _INT_KEY]
    parts += [str(Decimal(row.get(column) or 0).quantize(_CENT)) for column in _MONEY_KEY]
    return hashlib.md5("\x1f".join(parts).encode(), usedforsecurity=False).digest()


def signed_for_pay(row: Mapping[str, Any]) -> Decimal:
    """The row's «К перечислению», negated on a refund — WB's own ``forPaySum`` rule."""
    amount = Decimal(row.get("ppvz_for_pay") or 0)
    return -amount if row.get("doc_type_name") == REFUND_DOC_TYPE else amount


@dataclass
class RowSet:
    """A multiset of settlement rows, by key, with the totals worth naming."""

    keys: Counter[bytes] = field(default_factory=Counter)
    for_pay: Decimal = Decimal(0)

    def add(self, row: Mapping[str, Any]) -> None:
        """Count one more row."""
        self.keys[row_key(row)] += 1
        self.for_pay += signed_for_pay(row)

    @classmethod
    def of(cls, rows: Iterable[Mapping[str, Any]]) -> RowSet:
        """Build from an iterable of rows."""
        result = cls()
        for row in rows:
            result.add(row)
        return result

    @property
    def count(self) -> int:
        """How many rows."""
        return sum(self.keys.values())

    @property
    def digest(self) -> str:
        """An order-free fingerprint of the whole set."""
        md5 = hashlib.md5(usedforsecurity=False)
        for key in sorted(self.keys.elements()):
            md5.update(key)
        return md5.hexdigest()


@dataclass(frozen=True)
class Difference:
    """What one set holds that the other does not."""

    only_file: Counter[bytes]
    only_ours: Counter[bytes]

    @property
    def same(self) -> bool:
        """Whether the two sets are the same rows."""
        return not self.only_file and not self.only_ours

    @property
    def file_extends_ours(self) -> bool:
        """Every row of ours is in the file, and the file has more — a pure gap."""
        return bool(self.only_file) and not self.only_ours


def difference(file: RowSet, ours: RowSet) -> Difference:
    """Compare the upload's rows with ours, as multisets."""
    return Difference(only_file=file.keys - ours.keys, only_ours=ours.keys - file.keys)


__all__ = [
    "KEY_COLUMNS",
    "Difference",
    "RowSet",
    "difference",
    "row_key",
    "signed_for_pay",
]
