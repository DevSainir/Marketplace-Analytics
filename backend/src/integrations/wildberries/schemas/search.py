"""Raw payload models for the public WB search host (search.wb.ru).

Verified live shape (2026-08-14, ``/exactmatch/ru/common/v14/search``):
``{"metadata": {"normquery": "носки", ...}, "products": [{"id": 706083150, ...},
...], "total": 111119}``. ``products`` is the ranked result page — its ORDER is
the whole payload's value here, so only the identity fields are modelled and
everything else (prices, sizes, promo flags) is ignored.

Version matters: ``v13`` and ``v5`` answered HTTP 429 for every request while
``v14`` served 200s from the same IP within the same minute, so the version is a
settings knob rather than a constant.
"""

from __future__ import annotations

from pydantic import Field

from src.integrations.wildberries.schemas.base import RawBase


class WBSearchProduct(RawBase):
    """One product slot in a ranked search-result page."""

    nm_id: int = Field(alias="id")
    name: str = Field(default="")
    brand: str = Field(default="")
    supplier_id: int = Field(default=0, alias="supplierId")


class WBSearchMetadata(RawBase):
    """The ``metadata`` envelope; only WB's own query normalization is used."""

    #: WB's normalized form of the typed query — the SAME phrase the advertising
    #: search clusters (``normQuery``) are keyed by, which is what lets a live
    #: position probe be lined up against our stored cluster history.
    norm_query: str = Field(default="", alias="normquery")


class WBSearchPage(RawBase):
    """One page of WB's public search results, in rank order."""

    metadata: WBSearchMetadata = Field(default_factory=WBSearchMetadata)
    products: list[WBSearchProduct] = Field(default_factory=list)
    total: int = Field(default=0)
