"""What the catalogue sync stores as a SKU's thumbnail, and what it refuses.

The value this pins is rendered straight into an ``<img src>`` on three screens
(the monitoring SKU search, "SKU comparison" and the per-SKU P&L), which is why
the two negative cases matter as much as the happy one: the rendition WB
advertises but does not serve, and a host that is not WB's.
"""

from __future__ import annotations

from src.integrations.wildberries.schemas import WBCard
from src.modules.monitoring.services.ingestion.catalog import _main_photo

NM_ID = 953770957
BIG = f"https://basket-44.wbbasket.ru/vol5352/part535233/{NM_ID}/images/big/1.webp"
HQ = f"https://basket-44.wbbasket.ru/vol5352/part535233/{NM_ID}/images/hq/1.webp"


def _card(photos: list[dict[str, str]]) -> WBCard:
    """A Content API card carrying the given gallery renditions."""
    return WBCard.model_validate({"nmID": NM_ID, "vendorCode": "M-TRX01", "photos": photos})


def test_the_stored_thumbnail_is_the_rendition_wb_actually_serves() -> None:
    """The main slot's ``big`` is stored, never the ``hq`` beside it.

    WB advertises an ``hq`` URL on every card and its CDN answers 404 for all of
    them (measured 2026-09-07). Storing the one that sounds bigger would leave
    every thumbnail on three screens silently broken.
    """
    card = _card([{"hq": HQ, "big": BIG}])

    assert _main_photo(card) == BIG


def test_the_first_gallery_slot_is_the_one_taken() -> None:
    """``photos[0]`` is the card's main photo — the rest are not the thumbnail."""
    second = BIG.replace("/1.webp", "/2.webp")
    card = _card([{"big": BIG}, {"big": second}])

    assert _main_photo(card) == BIG


def test_a_card_with_no_images_stores_no_thumbnail() -> None:
    """An imageless card is catalogued photo-less rather than skipped."""
    card = _card([])

    assert _main_photo(card) == ""


def test_a_url_off_wbs_hosts_is_stored_as_no_thumbnail() -> None:
    """A non-WB host is dropped, not persisted for the browser to fetch.

    The URL arrives inside a WB response, which is outside the trust boundary
    however well authenticated the call was. Persisting an arbitrary host would
    put a third party's request inside our own page on every SKU screen, told
    which of our users is looking at which card.
    """
    card = _card([{"big": "https://wbbasket.ru.evil.example/vol1/images/big/1.webp"}])

    assert _main_photo(card) == ""


def test_a_plain_http_wb_url_is_stored_as_no_thumbnail() -> None:
    """https only — a mixed-content image is blocked by the browser anyway."""
    card = _card([{"big": BIG.replace("https://", "http://")}])

    assert _main_photo(card) == ""
