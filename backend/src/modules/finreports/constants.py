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


# --------------------------------------------------------------------------- #
# P&L operation taxonomy
# --------------------------------------------------------------------------- #
# Which ``supplier_oper_name`` values feed which line of the statement. Derived
# by aggregating every money column against every operation over the seller's
# whole settled history (436 742 rows / 133 reports / 2024-01-29..2026-07-26):
# each money column is populated by exactly one family of operations and is zero
# on all the others, which is what makes these groupings a partition rather than
# a guess.
#
# An operation missing from every tuple below contributes nothing to the
# statement, so the P&L service asserts the reverse: any operation it meets that
# is in none of these lists is reported as unclassified rather than dropped.

#: Units and revenue. ``quantity`` is 1 on every one of these rows.
SALE_OPERS: tuple[str, ...] = ("Продажа",)

#: Refunds. WB serves these POSITIVE — money and units alike — so every one of
#: them is subtracted, never summed with the sales.
RETURN_OPERS: tuple[str, ...] = ("Возврат",)

#: ``delivery_rub``. «Коррекция логистики» is the only one that goes negative.
LOGISTICS_OPERS: tuple[str, ...] = ("Логистика", "Коррекция логистики")

#: ``storage_fee``.
STORAGE_OPERS: tuple[str, ...] = ("Хранение", "Коррекция хранения", "Пересчет хранения")

#: ``acceptance``.
ACCEPTANCE_OPERS: tuple[str, ...] = (
    "Платная приемка",
    "Пересчет платной приемки",
    "Обработка товара",
)

#: ``penalty``.
PENALTY_OPERS: tuple[str, ...] = ("Штраф",)

#: ``deduction`` — WB's service invoices, overwhelmingly advertising.
DEDUCTION_OPERS: tuple[str, ...] = ("Удержание",)

#: ``rebill_logistic_cost``. Retired by WB after 2025-05-10; every row carries
#: ``nm_id = 0`` and a constant ``quantity = 2``, so it is company-level money
#: that can never be attributed to a SKU.
REBILL_OPERS: tuple[str, ...] = (
    "Возмещение издержек по перевозке/по складским операциям с товаром",
)

#: Standalone compensations WB pays or withholds outside the sale/return flow.
#: They carry ``quantity = 1`` but share their ``srid`` with no sale, so they are
#: money-only: counting them as units would inflate COGS against stock that was
#: never shipped.
COMPENSATION_OPERS: tuple[str, ...] = (
    "Добровольная компенсация при возврате",
    "Компенсация ущерба",
    "Частичная компенсация брака",
    "Компенсация брака",
    "Компенсация подмененного товара",
    "Компенсация потерянного товара",
    "Компенсация скидки по программе лояльности",
    "Авансовая оплата за товар без движения",
    "Возмещение за выдачу и возврат товаров на ПВЗ",
    "Корректировка эквайринга",
    "Коррекция продаж",
    "Коррекция возвратов",
)

#: Every operation the statement knows how to place.
CLASSIFIED_OPERS: frozenset[str] = frozenset(
    SALE_OPERS
    + RETURN_OPERS
    + LOGISTICS_OPERS
    + STORAGE_OPERS
    + ACCEPTANCE_OPERS
    + PENALTY_OPERS
    + DEDUCTION_OPERS
    + REBILL_OPERS
    + COMPENSATION_OPERS
)


# --------------------------------------------------------------------------- #
# Deduction reasons
# --------------------------------------------------------------------------- #
# «Удержание» is one operation carrying several unrelated costs, told apart only
# by the free-text ``bonus_type_name`` — which embeds an invoice number, so the
# match has to be by substring. Advertising alone is 5 979 875 of the 7 862 125
# KGS ever withheld (95 %), and burying it inside «прочие удержания» would hide
# the seller's single largest controllable cost.
#
# Substring matching against WB's prose is fragile by nature. It is safe *here*
# because an unrecognised label falls through to «Прочие удержания» — a renamed
# invoice line shows up in the wrong bucket, never disappears from the total.

#: Marketing spend billed through «ВБ.Продвижение».
ADVERTISING_DEDUCTION_MARKER: str = "Продвижение"

#: The «Джем» seller-subscription fee.
SUBSCRIPTION_DEDUCTION_MARKER: str = "Джем"

#: Inbound transit delivery of supplies to the warehouse.
TRANSIT_DEDUCTION_MARKER: str = "транзитных поставок"


# --------------------------------------------------------------------------- #
# Acquiring: withheld vs billed separately
# --------------------------------------------------------------------------- #
#: ``payment_processing`` value marking an ``acquiring_fee`` that WB does NOT
#: withhold from ``ppvz_for_pay``.
#:
#: Measured, not assumed. Over the whole 620k-row history the payout identity
#: ``ppvz_for_pay = retail_amount - ppvz_vw - ppvz_vw_nds - acquiring_fee -
#: ppvz_reward`` fails on 5 727 rows, and on 3 293 of them the residual equals
#: ``acquiring_fee`` to the kopeck — every single one carrying this label. Its
#: three siblings («Перевыставление эквайринга», «Компенсация платёжных услуг»,
#: blank) break the identity on 102 rows in total.
#:
#: So this fee is billed elsewhere. Subtracting it from the payout as if it were
#: withheld overstates the seller's acquiring cost by 226 004 KGS across the
#: history and understates WB's commission by the same amount.
SEPARATELY_BILLED_ACQUIRING: str = "Комиссия за организацию платежа с НДС"
