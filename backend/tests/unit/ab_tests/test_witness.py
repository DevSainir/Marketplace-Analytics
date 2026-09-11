"""Unit tests for the photo witness (ab_tests/services/witness.py).

Every case here is about the same asymmetry. A witness that misses a foreign
edit costs the seller a table of numbers credited to the wrong picture; a
witness that *invents* one stops a running test over a CDN hiccup. The second is
the worse failure, so «cannot tell» has to be indistinguishable from «all is
well» to the caller, and that is what most of these pin.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.modules.ab_tests.services.witness import CONFIRM_ATTEMPTS, PhotoWitness

URL = "https://basket-45.wbbasket.ru/vol19442/part1944299/1944299862/images/big/1.webp"
PUBLISHED = datetime(2026, 9, 10, 7, 45, 3, tzinfo=UTC)
HEADER = "Thu, 10 Sep 2026 07:45:03 GMT"
EARLIER = "Wed, 09 Sep 2026 11:58:18 GMT"


def _client(handler: object) -> httpx.AsyncClient:
    """An async client answering from a handler rather than the network."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def _answer(**headers: str) -> object:
    """A handler returning 200 with the given headers."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers)

    return handle


async def test_the_cdns_last_modified_is_what_the_witness_reports() -> None:
    """A 200 with a Last-Modified yields that moment, parsed and aware."""
    async with _client(_answer(**{"last-modified": HEADER})) as client:
        observed = await PhotoWitness(client=client).observe(URL)

    assert observed == PUBLISHED


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://evil.example/vol1/part1/1/images/big/1.webp",
        "https://notwbbasket.ru/images/big/1.webp",
        "https://wbbasket.ru.evil.example/images/big/1.webp",
        "http://basket-45.wbbasket.ru/images/big/1.webp",
    ],
)
async def test_a_url_that_is_not_a_wb_photo_is_never_fetched(url: str) -> None:
    """Anything but an https WB image host answers None without a request.

    The URL reaches this code out of the database, having come from WB's own
    payload before that. Fetching whatever an upstream names is SSRF, and the
    transport below fails the test loudly rather than quietly allowing it.
    """

    def handle(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"the witness fetched {request.url}")

    async with _client(handle) as client:
        assert await PhotoWitness(client=client).observe(url) is None


async def test_an_unreachable_cdn_means_cannot_tell_rather_than_mismatch() -> None:
    """A transport failure answers None, which stands the guard down.

    This is the case that decides whether the guard is safe to run in a poller
    at all: a network blip must not be able to stop a seller's test.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with _client(handle) as client:
        assert await PhotoWitness(client=client).observe(URL) is None


@pytest.mark.parametrize("status", [403, 404, 500, 503])
async def test_a_non_200_means_cannot_tell(status: int) -> None:
    """The witness only speaks for a 200; anything else is silence."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"last-modified": HEADER})

    async with _client(handle) as client:
        assert await PhotoWitness(client=client).observe(URL) is None


@pytest.mark.parametrize("header", ["", "not a date", "Thu, 32 Sep 2026 07:45:03 GMT"])
async def test_a_header_that_will_not_parse_means_cannot_tell(header: str) -> None:
    """A malformed date is silence, not an exception.

    WB has never sent one; the poller must not be the place that finds out what
    happens if it does.
    """
    async with _client(_answer(**{"last-modified": header})) as client:
        assert await PhotoWitness(client=client).observe(URL) is None


async def test_a_missing_header_means_cannot_tell() -> None:
    """A 200 carrying no Last-Modified at all answers None."""
    async with _client(_answer()) as client:
        assert await PhotoWitness(client=client).observe(URL) is None


async def test_confirming_an_install_waits_for_the_timestamp_to_move() -> None:
    """The confirmation returns only a value that differs from the old one.

    Reading once would race the edge: publication is same-second at the origin
    but the value this process sees may be the previous one for a few seconds,
    and storing THAT would make the next pass report a conflict against our own
    photo. Here the first two reads are stale and the third is ours.
    """
    seen: list[str] = [EARLIER, EARLIER, HEADER]

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"last-modified": seen.pop(0)})

    async with _client(handle) as client:
        confirmed = await PhotoWitness(client=client, confirm_delay=0).confirm_install(
            URL, was=datetime(2026, 9, 9, 11, 58, 18, tzinfo=UTC)
        )

    assert confirmed == PUBLISHED
    assert not seen, "the confirmation stopped before the timestamp moved"


async def test_a_timestamp_that_never_moves_leaves_the_turn_unwitnessed() -> None:
    """Giving up stores None rather than the stale value.

    None disables the check for that turn. The stale value would arm it against
    a photo we know is not the one we installed, and report a conflict on the
    very next pass — the guard accusing the rotation of its own work.
    """
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"last-modified": EARLIER})

    async with _client(handle) as client:
        confirmed = await PhotoWitness(client=client, confirm_delay=0).confirm_install(
            URL, was=datetime(2026, 9, 9, 11, 58, 18, tzinfo=UTC)
        )

    assert confirmed is None
    assert calls == CONFIRM_ATTEMPTS


async def test_with_nothing_to_compare_against_the_first_reading_is_taken() -> None:
    """When there was no previous timestamp, the first answer is the answer.

    A card whose photo we have never witnessed — the first install of a test —
    has no stale value to be mistaken for, so waiting for a change would burn
    the whole retry budget and then report nothing.
    """
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={"last-modified": HEADER})

    async with _client(handle) as client:
        confirmed = await PhotoWitness(client=client, confirm_delay=0).confirm_install(
            URL, was=None
        )

    assert confirmed == PUBLISHED
    assert calls == 1
