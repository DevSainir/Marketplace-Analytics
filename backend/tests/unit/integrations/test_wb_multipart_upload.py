"""The one WB call that sends a body which is not JSON.

`POST /content/v3/media/file` is a multipart upload — the only write the A/Б
photo rotation makes, and the only non-JSON request in any WB client. It was
answered 400 by WB for as long as the feature existed, because the transport
put `Content-Type: application/json` in the CLIENT's default headers: httpx
fills a `Content-Type` in from the body only when none is present, and a
client-level default is never absent, so the multipart body went out labelled
as JSON.

Nothing below mocks the header merging — that IS the bug — so these drive a real
`httpx.AsyncClient` through a `MockTransport` and read what would have gone over
the wire.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx

from src.integrations.wildberries.clients.content import WBContentClient


def _settings(**overrides: Any) -> SimpleNamespace:
    """A stand-in for :class:`Settings` exposing only what the client reads."""
    base = {
        "wb_content_base_url": "https://content-api.wildberries.ru",
        "wb_http_timeout_seconds": 30.0,
        "wb_max_retries": 1,
        "wb_retry_backoff_seconds": 0.0,
        "wb_retry_max_backoff_seconds": 0.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _recording_client(seen: list[httpx.Request]) -> WBContentClient:
    """A content client whose transport records the request instead of sending."""
    client = WBContentClient(_settings(), token="test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/cards/list"):
            # A short page, so `fetch_all_cards` stops after one round trip.
            return httpx.Response(200, json={"cards": [], "cursor": {"total": 0}})
        return httpx.Response(200, json={"data": {}, "error": False})

    client._client = httpx.AsyncClient(
        base_url=client._client.base_url,
        headers=client._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return client


async def test_a_photo_upload_is_labelled_multipart() -> None:
    """The upload must carry the multipart content type httpx computed for it.

    With `application/json` on the client defaults WB answers 400 — verified
    live on 2026-09-05, same bytes and token, 400 with the header and 200
    without it eight seconds later.
    """
    seen: list[httpx.Request] = []
    client = _recording_client(seen)

    await client.upload_media_file(
        nm_id=909379884,
        photo_number=1,
        content=b"\xff\xd8\xff\xe0 not really a jpeg",
        filename="variant.jpg",
        content_type="image/jpeg",
    )

    assert len(seen) == 1
    content_type = seen[0].headers["content-type"]
    assert content_type.startswith("multipart/form-data"), content_type
    assert "boundary=" in content_type


async def test_the_upload_names_the_card_and_the_slot_in_headers() -> None:
    """WB takes the target out of headers, not the body; slot 1 is the main photo."""
    seen: list[httpx.Request] = []
    client = _recording_client(seen)

    await client.upload_media_file(
        nm_id=909379884,
        photo_number=1,
        content=b"bytes",
        filename="variant.jpg",
        content_type="image/jpeg",
    )

    assert seen[0].headers["X-Nm-Id"] == "909379884"
    assert seen[0].headers["X-Photo-Number"] == "1"
    assert seen[0].headers["Authorization"] == "test-token"


async def test_a_json_call_still_declares_json() -> None:
    """Removing the default must not leave the JSON endpoints unlabelled.

    httpx sets `application/json` from the `json=` body itself, so the fix costs
    the other twenty-odd endpoints nothing — but only a test says so.
    """
    seen: list[httpx.Request] = []
    client = _recording_client(seen)

    await client.fetch_all_cards()

    assert seen[0].headers["content-type"] == "application/json"
