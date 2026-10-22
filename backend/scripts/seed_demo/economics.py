"""What one sold unit is worth, split the way WB's settlement report splits it.

The P&L reads these figures straight off the settlement rows, so they have to
satisfy the identity WB's own rows satisfy (``docs/finreports/PNL.md``):

    payout = paid - commission (net of VAT) - its VAT - acquiring - reward

The proportions are a small apparel seller's: WB's discount (SPP) comes out of
WB's commission, so the seller's payout tracks the SELLER's price while the
buyer pays less — which is why WB's net commission here is only a few percent
of what the buyer paid.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from scripts.seed_demo import simulation as sim
from scripts.seed_demo.catalogue import DemoSku

#: WB's net commission, as a share of what the buyer paid.
_NET_COMMISSION = Decimal("0.045")
#: The VAT inside that commission (22 % in Russia from 2026).
_VAT = Decimal("1.22")
#: Acquiring, as a share of what the buyer paid.
_ACQUIRING = Decimal("0.015")
#: The commission rate WB publishes for the category, before SPP is taken out.
COMMISSION_PERCENT = Decimal("24.50")


@dataclass(frozen=True)
class SaleAmounts:
    """One unit's money, as the settlement row carries it.

    Attributes:
        list_price: The card's «before discount» price (``retail_price``).
        seller_price: The seller's price (``retail_price_withdisc_rub``).
        paid: What the buyer paid after WB's discount (``retail_amount``).
        spp: WB's discount, percent (``ppvz_spp_prc``).
        sale_percent: The seller's own discount, percent.
        commission: WB's commission net of VAT (``ppvz_vw``, ten places).
        commission_vat: The VAT on it (``ppvz_vw_nds``).
        acquiring: The payment fee (``acquiring_fee``).
        payout: What WB transfers to the seller (``ppvz_for_pay``).
    """

    list_price: Decimal
    seller_price: Decimal
    paid: Decimal
    spp: Decimal
    sale_percent: Decimal
    commission: Decimal
    commission_vat: Decimal
    acquiring: Decimal
    payout: Decimal


def sale_amounts(sku: DemoSku, order_day: date) -> SaleAmounts:
    """The settlement split of one unit ordered on ``order_day``."""
    seller = sim.seller_price(sku, order_day)
    paid = sim.customer_price(sku, order_day)
    gross_commission = sim.money(paid * _NET_COMMISSION)
    commission = (gross_commission / _VAT).quantize(Decimal("1e-10"), rounding=ROUND_HALF_UP)
    commission_vat = sim.money(gross_commission - commission)
    acquiring = sim.money(paid * _ACQUIRING)
    return SaleAmounts(
        list_price=sku.list_price,
        seller_price=seller,
        paid=paid,
        spp=sim.spp_percent(sku, order_day),
        sale_percent=sim.money((1 - seller / sku.list_price) * 100),
        commission=commission,
        commission_vat=commission_vat,
        acquiring=acquiring,
        payout=paid - gross_commission - acquiring,
    )
