"""Shared constants for the ``finreports`` module.

Neutral values imported by both the data-access and service layers (so neither
depends on the other). The Cyrillic strings are the exact WB-served labels the
``reportDetailByPeriod``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

#: WB ``supplier_oper_name`` for a logistics (delivery) charge.
LOGISTICS_OPER: str = "Логистика"

#: WB ``supplier_oper_name`` for a penalty row.
PENALTY_OPER: str = "Штраф"



#: FX-invariant), and WB currently sets these uniformly across warehouses
#: (verified live 2026-07-22: base 46, litre 14).
DEFAULT_BOX_DELIVERY_BASE: Decimal = Decimal("46")
DEFAULT_BOX_DELIVERY_LITER: Decimal = Decimal("14")

#: money: ``(in force from, annual rate)``, ascending, each rate running until
#: the next entry.
#:
#: .. warning::
#:    **This table is an input to a legal document and MUST be verified against
#:    cbr.ru before the claim is filed.** It is checked in so the calculation is
#:    reproducible and reviewable, not because the application can prove it: no
#:    WB API serves it, so nothing here is validated against a live source the
#:    way every other figure in this module is. The methodology sheet prints the
#:    calendar in full, and :data:`KEY_RATE_VERIFIED_THROUGH` is stated next to
#:    every interest figure, precisely so a reader checks rather than trusts.
#:
#:    Jurisdiction matters too: this seller contracts under the Kyrgyz edition of
#:    the WB offer. If the applicable law is not Russian, both the rate source
#:    Interest is therefore reported as a SEPARATE line and is never folded into
KEY_RATE_CALENDAR: tuple[tuple[date, Decimal], ...] = (
    (date(2023, 12, 18), Decimal("0.16")),
    (date(2024, 7, 29), Decimal("0.18")),
    (date(2024, 9, 16), Decimal("0.19")),
    (date(2024, 10, 28), Decimal("0.21")),
    (date(2025, 6, 9), Decimal("0.20")),
    (date(2025, 7, 28), Decimal("0.18")),
    (date(2025, 9, 15), Decimal("0.17")),
    (date(2025, 10, 27), Decimal("0.165")),
)

#: Last date the calendar above was checked against the primary source. Beyond
#: it the final rate is simply carried forward, which is an assumption, not a
#: fact — so it is printed wherever an interest figure is.
KEY_RATE_VERIFIED_THROUGH: date = date(2025, 10, 27)
