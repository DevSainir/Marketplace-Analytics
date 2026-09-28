"""Raw payload models for the WB Content surface (product cards).

Content — product cards: ``POST /content/v2/get/cards/list``.

Verified live shape (2026-07): {"cards": [ {nmID, vendorCode, title,
brand, sizes: [{chrtID, techSize, wbSize, skus}], ...}, ... ],
"cursor": {updatedAt, nmID, total}}. This is the authoritative source for
the human-readable vendor code (``Артикул продавца``) and size label
(``Размер вещи`` == ``techSize``); the stocks endpoint carries only chrtID.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBCardDimensions(RawBase):
    """A card's declared package dimensions (cm) and gross weight (kg).

    ``finreports`` module prices logistics against. ``is_valid`` is WB's own
    completeness flag on the dimensions block.
    """

    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    weight_brutto: Decimal | None = Field(default=None, alias="weightBrutto")
    is_valid: bool = Field(default=False, alias="isValid")


class WBCardSize(RawBase):
    """One size variant of a product card.

    ``tech_size`` is WB's human size label (the seller-portal "Размер вещи"
    column, e.g. ``"52/170-177"`` / ``"L"`` / ``"42"``); ``wb_size`` is WB's
    alternate scale (e.g. ``"2XL/ 170-177"`` / ``"46"``). ``chrt_id`` is the
    join key back to the label-less stock rows.
    """

    chrt_id: int = Field(alias="chrtID")
    tech_size: str = Field(default="", alias="techSize")
    wb_size: str = Field(default="", alias="wbSize")
    # Barcodes of this size. WB has always returned them here; we started
    # persisting one because the FBS stock endpoint is queried BY barcode —
    # ``chrt_id`` gets us everywhere else, but not there.
    skus: list[str] = Field(default_factory=list)


class WBCardPhoto(RawBase):
    """One gallery image of a card, as WB's own CDN serves it.

    WB returns a URL per rendition rather than the seller's original upload —
    everything here is a transcoded ``.webp`` on ``basket-NN.wbbasket.ru``,
    public and unauthenticated.

    **``hq`` is advertised and not served.** Measured 2026-09-07 across three
    cards of the ``Демо`` catalogue: every payload carried an ``hq`` URL and
    every one answered ``404 text/html``, while ``big``, ``c516x688``,
    ``c246x328``, ``square`` and ``tm`` all answered ``200 image/webp``. A URL
    being present therefore says nothing about the file existing, and ``big`` —
    68-118 KB, the largest that does — is what to take. Preferring ``hq``
    because it sounds bigger cost a silent capture failure: the A/Б module reads
    a failed fetch as "this card has no baseline", so every test would have
    quietly run without one.
    """

    hq: str = Field(default="")
    big: str = Field(default="")
    square: str = Field(default="")
    tm: str = Field(default="")

    @property
    def best(self) -> str:
        """The largest rendition WB actually serves, or ``""`` when it sent none.

        ``big`` first, deliberately — see the class docstring for the ``hq``
        404. The rest are fallbacks for a payload shaped unlike the ones
        measured, in descending size.
        """
        return self.big or self.square or self.tm or self.hq


class WBCard(RawBase):
    """A product card: nmID identity, seller vendor code, title, photos, sizes.

    ``photos`` is in **gallery slot order** — ``photos[0]`` is the card's main
    photo, the slot ``POST /content/v3/media/file`` writes with
    ``photo_number=1``. Empty for a card WB holds no images for.
    """

    nm_id: int = Field(alias="nmID")
    vendor_code: str = Field(default="", alias="vendorCode")
    title: str = Field(default="", alias="title")
    #: WB's «Предмет» (e.g. «Костюмы»). What the heatmap's «Категории» filter
    #: and «По категории» cut group by; blank when WB returns none.
    subject_name: str = Field(default="", alias="subjectName")
    brand: str = Field(default="", alias="brand")
    dimensions: WBCardDimensions | None = None
    photos: list[WBCardPhoto] = Field(default_factory=list)
    sizes: list[WBCardSize] = Field(default_factory=list)
