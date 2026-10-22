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

#: ``doc_type_name`` of a refund row, and the ``supplier_oper_name`` of a return.
REFUND = "Возврат"
#: ``supplier_oper_name`` of a sale.
SALE = "Продажа"
#: ``supplier_oper_name`` of a delivery charge.
LOGISTICS = "Логистика"

#: Advertising ``paymentType``: paid out of WB's bonus pool.
CASHBACK = "Кэшбэк"
#: Advertising ``paymentType``: paid from the seller's own balance.
BALANCE = "Баланс"
