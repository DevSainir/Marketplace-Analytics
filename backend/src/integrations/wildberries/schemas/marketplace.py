"""Raw payload models for the WB Marketplace (FBS) surface.

FBS is the fulfilment mode where stock sits in the **seller's own** warehouse
rather than WB's. It is a different API surface with its own token category
(«Маркетплейс»), and — verified live on 2026-08-13 — it is the ONLY one that
reports that stock: the Поставки surface answers with WB's acceptance
directory, and the analytics remains report excludes FBS entirely — its
grand-total row matched the sum of the FBO warehouses to the unit, so FBS
contributes nothing there rather than being merely unlabelled.
"""

from __future__ import annotations

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBFbsWarehouse(RawBase):
    """One seller-owned (FBS) warehouse.

    Attributes:
        id: WB's warehouse id — the path parameter of the stocks endpoint and
            the only stable handle. Names are seller-authored working notes
            («Иван  - Москва (Внуково) НЕ УДАЛЯТЬ!!!») and get edited in the
            portal, so nothing may key on them.
        name: The seller's own label for the warehouse.
        office_id: The linked WB pickup office.
        cargo_type: WB cargo classification.
        delivery_type: Fulfilment scheme — observed ``1`` for FBS and ``6`` for
            the EDBS (cross-border) warehouse on the same account, so this is
            not a constant.
    """

    id: int
    name: str = Field(default="")
    office_id: int = Field(default=0, alias="officeId")
    cargo_type: int = Field(default=0, alias="cargoType")
    delivery_type: int = Field(default=0, alias="deliveryType")


class WBFbsStockRow(RawBase):
    """Remaining units of one barcode at one FBS warehouse.

    Attributes:
        sku: The barcode that was asked for (WB echoes it back).
        chrt_id: WB's size characteristic id — returned by this endpoint, which
            is what lets an FBS row join ``monitoring.product_size`` directly
            without a barcode mapping table of our own.
        amount: Units on hand. There is no in-transit counterpart here: FBS
            stock sits in the seller's warehouse, so the ``in_way_*`` columns
            an FBO row carries have no source on this surface.
    """

    sku: str = Field(default="")
    chrt_id: int = Field(default=0, alias="chrtId")
    amount: int = Field(default=0)
