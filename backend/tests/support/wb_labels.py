"""WB's own Russian labels, as tests feed them in.

Wildberries serves several fields as Russian text that the code classifies by
exact string — an operation name, a document type, an advertising payment
type. A test that builds such a row needs the literal WB would send, and this
module is the one place the tests keep them, so the rest of the suite reads in
English and names the label instead of spelling it.

Written out here rather than imported from ``src``: a test that took its input
from the constant it checks would pass with a typo in that constant — the one
mistake that silently drops an operation from the P&L in production.
"""

from __future__ import annotations

# --- Weekly settlement report: ``supplier_oper_name`` / ``doc_type_name`` ---

#: ``doc_type_name`` of a refund row, and the ``supplier_oper_name`` of a return.
REFUND = "Возврат"
#: ``doc_type_name`` and ``supplier_oper_name`` of a sale.
SALE = "Продажа"
#: A delivery charge, and its correction.
LOGISTICS = "Логистика"
LOGISTICS_CORRECTION = "Коррекция логистики"
#: Storage, its correction and its recalculation.
STORAGE = "Хранение"
STORAGE_CORRECTION = "Коррекция хранения"
STORAGE_RECALCULATION = "Пересчет хранения"
#: Paid acceptance, its recalculation, and goods processing.
ACCEPTANCE = "Платная приемка"
ACCEPTANCE_RECALCULATION = "Пересчет платной приемки"
GOODS_PROCESSING = "Обработка товара"
#: A penalty.
PENALTY = "Штраф"
#: A deduction (advertising, subscriptions, transit supplies…).
DEDUCTION = "Удержание"
#: WB re-billing the seller for transport or warehouse costs.
REBILL = "Возмещение издержек по перевозке/по складским операциям с товаром"
#: Compensations WB pays the seller.
VOLUNTARY_RETURN_COMPENSATION = "Добровольная компенсация при возврате"
DAMAGE_COMPENSATION = "Компенсация ущерба"
PARTIAL_DEFECT_COMPENSATION = "Частичная компенсация брака"
DEFECT_COMPENSATION = "Компенсация брака"
SWAPPED_GOODS_COMPENSATION = "Компенсация подмененного товара"
LOST_GOODS_COMPENSATION = "Компенсация потерянного товара"
LOYALTY_DISCOUNT_COMPENSATION = "Компенсация скидки по программе лояльности"
IDLE_GOODS_ADVANCE = "Авансовая оплата за товар без движения"
PICKUP_POINT_REFUND = "Возмещение за выдачу и возврат товаров на ПВЗ"
ACQUIRING_CORRECTION = "Корректировка эквайринга"
SALES_CORRECTION = "Коррекция продаж"
RETURNS_CORRECTION = "Коррекция возвратов"

# --- Weekly settlement report: markers inside ``bonus_type_name`` ---

#: The advertising deduction ("WB Promotion" services).
ADVERTISING_MARKER = "Продвижение"
#: The "Jam" subscription.
SUBSCRIPTION_MARKER = "Джем"
#: Delivery of transit supplies.
TRANSIT_MARKER = "транзитных поставок"
#: A whole advertising deduction line as WB writes it, marker included.
ADVERTISING_DEDUCTION = "Оказание услуг «WB Продвижение»"

#: ``payment_processing`` of acquiring billed separately.
SEPARATELY_BILLED_ACQUIRING = "Комиссия за организацию платежа с НДС"

# --- Advertising write-offs: ``paymentType`` ---

#: Paid out of WB's bonus pool.
CASHBACK = "Кэшбэк"
#: Paid out of WB's bonus pool, under its other name.
BONUSES = "Бонусы"
#: Paid from the seller's own balance.
BALANCE = "Баланс"
#: Paid from the seller's account, in both spellings WB uses.
ACCOUNT = "Счет"
ACCOUNT_WITH_YO = "Счёт"

# --- Order feed: ``regionName`` ---

#: The Moscow region, the storefront prices are read for.
MOSCOW = "Москва"
MOSCOW_REGION = "Московская область"
