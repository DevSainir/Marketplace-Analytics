"""Unit tests for the WB public-search position probe.

No network: the page fetch is stubbed. What these pin is the arithmetic and the
failure policy — a position spanning pages, and the difference between "your SKU
does not rank" and "WB did not answer", which the panel must never conflate.
"""

from __future__ import annotations

import httpx
import pytest

from src.core.config import Settings
from src.core.exceptions import IntegrationError
from src.integrations.wildberries.clients.base import scrub_credentials
from src.integrations.wildberries.clients.search import WBPublicSearchClient
from src.integrations.wildberries.schemas import (
    WBSearchMetadata,
    WBSearchPage,
    WBSearchProduct,
)

OURS = 953770957
ALSO_OURS = 144178006


def _settings(**overrides: object) -> Settings:
    """Settings with a small page size so a two-page scan stays readable."""
    return Settings(wb_search_page_size=3, wb_search_max_pages=3, **overrides)  # type: ignore[arg-type]


def _page(*nm_ids: int, total: int = 99, normquery: str = "носки") -> WBSearchPage:
    """A ranked result page holding the given SKUs in order."""
    return WBSearchPage(
        metadata=WBSearchMetadata(norm_query=normquery),
        products=[WBSearchProduct(nm_id=nm_id) for nm_id in nm_ids],
        total=total,
    )


def _client(pages: list[WBSearchPage | IntegrationError]) -> WBPublicSearchClient:
    """A client whose page fetch replays ``pages`` (raising the error entries)."""
    client = WBPublicSearchClient(_settings())

    async def fake_fetch(*, query: str, page: int) -> WBSearchPage:
        result = pages[page - 1]
        if isinstance(result, IntegrationError):
            raise result
        return result

    client._fetch_page = fake_fetch  # type: ignore[method-assign]
    return client


async def test_a_position_on_the_second_page_continues_the_first_pages_numbering() -> None:
    """Page 2, slot 2 at 3 per page is position 5 — what a seller means by «позиция»."""
    client = _client([_page(1, 2, 3), _page(4, OURS, 6)])

    probe = await client.find_positions(query="носки", nm_ids={OURS})

    assert probe.positions[0].position == 5
    assert (probe.positions[0].page, probe.positions[0].position_on_page) == (2, 2)


async def test_the_scan_stops_once_every_asked_for_sku_is_located() -> None:
    """Each extra page costs rate budget the probe does not need to spend."""
    client = _client([_page(OURS, ALSO_OURS, 3), _page(4, 5, 6), _page(7, 8, 9)])

    probe = await client.find_positions(query="носки", nm_ids={OURS, ALSO_OURS})

    assert probe.pages_scanned == 1
    assert [position.nm_id for position in probe.positions] == [OURS, ALSO_OURS]


async def test_a_short_page_ends_the_scan_and_marks_the_result_complete() -> None:
    """WB ran out of results, so nothing was missed — `truncated` must be False.

    The flag is what lets the UI say «нет в выдаче» instead of «не найдено в
    просмотренных позициях», and only an exhausted result set justifies that.
    """
    client = _client([_page(1, 2, 3, total=4), _page(4, total=4)])

    probe = await client.find_positions(query="носки", nm_ids={OURS})

    assert probe.pages_scanned == 2
    assert probe.truncated is False
    assert probe.positions == []


async def test_more_results_than_scanned_is_reported_as_truncated() -> None:
    """A SKU missing from a bounded scan may still rank deeper, and must say so."""
    client = _client([_page(1, 2, 3), _page(4, 5, 6), _page(7, 8, 9)])

    probe = await client.find_positions(query="носки", nm_ids={OURS})

    assert probe.positions_scanned == 9
    assert probe.truncated is True


async def test_a_failure_on_the_first_page_is_raised_not_reported_as_absent() -> None:
    """Nothing was learned, so answering "not found" would be a fabrication."""
    client = _client([IntegrationError("429 forever")])

    with pytest.raises(IntegrationError):
        await client.find_positions(query="носки", nm_ids={OURS})


async def test_a_throttled_first_page_says_so_in_the_words_the_panel_shows() -> None:
    """A throttled probe must read as "retry", not as "broken" or "ranks nowhere".

    The transport error stays as the exception's cause: the log keeps "429", the
    seller reads a sentence telling them what to do about it.
    """
    cause = IntegrationError("GET /exactmatch failed after 2 attempts: HTTP 429")
    client = WBPublicSearchClient(_settings())

    async def fake_request(*args: object, **kwargs: object) -> dict[str, object]:
        raise cause

    client._request = fake_request  # type: ignore[method-assign]

    with pytest.raises(IntegrationError, match="Повторите через минуту") as raised:
        await client.find_positions(query="носки", nm_ids={OURS})

    assert raised.value.__cause__ is cause


def test_the_probe_goes_direct_even_when_the_card_endpoint_is_proxied() -> None:
    """Regression: proxying this host CAUSED the throttling it was meant to dodge.

    Measured from prod 2026-08-15, same query seconds apart — direct answered 200
    with a full page, the residential proxy answered 429. search.wb.ru does not
    block datacenter egress the way card.wb.ru does; it rate-limits per IP, and a
    shared proxy exit arrives with its budget already spent.
    """
    settings = _settings(wb_card_proxy="http://user:pass@residential.example:8000")

    assert WBPublicSearchClient.resolve_proxy(settings) == ""


def test_card_opts_back_into_the_shared_proxy_credential() -> None:
    """The escape hatch if this host ever starts blocking us too — one credential."""
    settings = _settings(
        wb_card_proxy="http://user:pass@residential.example:8000",
        wb_search_proxy="card",
    )

    assert (
        WBPublicSearchClient.resolve_proxy(settings) == "http://user:pass@residential.example:8000"
    )


def test_a_proxy_url_never_reaches_a_log_with_its_credentials() -> None:
    """Transport errors quote the tunnel URL verbatim, password included."""
    failure = "ProxyError: http://user:hunter2@residential.example:8000 refused the tunnel"

    assert "hunter2" not in scrub_credentials(failure)
    assert "residential.example:8000" in scrub_credentials(failure)


def test_the_probe_never_waits_out_a_retry_after_the_way_the_harvest_does() -> None:
    """A watched request caps the server's demanded wait; the harvest honours it.

    Regression: ``max_retries`` alone bounded nothing, because a demanded wait is
    honoured PAST the backoff cap — an unbounded ``Retry-After`` would hang the
    page. The cap is one throttle window, not a token gesture: a 1.5s retry was
    refused every time on prod because this host's window is tens of seconds.
    """
    settings = _settings()
    probe = WBPublicSearchClient(settings)
    demanded = httpx.Response(429, headers={"Retry-After": "900"})

    waited = probe._retry_delay(attempt=0, response=demanded)

    assert waited == settings.wb_search_retry_max_backoff_seconds
    assert waited < 900


async def test_a_failure_on_a_later_page_keeps_what_was_already_found() -> None:
    """Positions from the pages that did answer are real; the depth reported shrinks."""
    client = _client([_page(1, OURS, 3), IntegrationError("throttled")])

    probe = await client.find_positions(query="носки", nm_ids={OURS, ALSO_OURS})

    assert probe.pages_scanned == 1
    assert [position.nm_id for position in probe.positions] == [OURS]


@pytest.mark.parametrize("total", [111119, 0])
async def test_an_empty_first_page_is_treated_as_a_block_not_as_a_ranking(total: int) -> None:
    """WB's throttled edge answers 200 with no products; that is not "nowhere".

    Verified live: one phrase was served an empty envelope with ``total: 0``, then
    100 products and ``total: 109542`` a minute later — so a zero total does not
    make an empty page trustworthy either. Passing either through would report
    every SKU as unranked.
    """
    client = WBPublicSearchClient(_settings())

    async def fake_request(*args: object, **kwargs: object) -> dict[str, object]:
        return {"metadata": {"normquery": "носки"}, "products": [], "total": total}

    client._request = fake_request  # type: ignore[method-assign]

    with pytest.raises(IntegrationError, match="пустую выдачу"):
        await client.find_positions(query="носки", nm_ids={OURS})
