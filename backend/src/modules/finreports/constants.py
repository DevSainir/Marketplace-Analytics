"""Shared constants for the ``finreports`` module.

Neutral values imported by both the data-access and service layers (so neither
depends on the other). The Cyrillic strings are the exact WB-served labels the
``reportDetailByPeriod``.
"""

from __future__ import annotations

from decimal import Decimal

#: WB ``supplier_oper_name`` for a logistics (delivery) charge.
LOGISTICS_OPER: str = "Логистика"

#: WB ``supplier_oper_name`` for a penalty row.
PENALTY_OPER: str = "Штраф"



#: FX-invariant), and WB currently sets these uniformly across warehouses
#: (verified live 2026-07-22: base 46, litre 14).
DEFAULT_BOX_DELIVERY_BASE: Decimal = Decimal("46")
DEFAULT_BOX_DELIVERY_LITER: Decimal = Decimal("14")
