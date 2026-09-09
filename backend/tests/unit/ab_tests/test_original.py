"""Unit tests for capturing the card's own main photo (services/original.py).

Two things are worth pinning here and nothing else is.

**It must never stop a start.** Everything on the way to the capture is
somebody else's infrastructure — WB's API, WB's CDN, whatever format they
transcoded the seller's upload into — and the fallback is the behaviour the
module had before any of this existed. A failure that raised would turn a
degraded test into no test.

**It must not fetch whatever it is told to.** The URL is chosen by an upstream,
so the host allowlist is the boundary between "read the seller's own card" and
"issue an arbitrary request from inside the network".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

import src.modules.ab_tests.deps as ab_deps
from src.core.ids import uuid7
from src.integrations.wildberries.photos import is_wb_photo_url
from src.integrations.wildberries.schemas import WBCardPhoto
from src.modules.ab_tests.models import AbTest, AbTestVariant
from src.modules.ab_tests.services.original import (
    ORIGINAL_FILENAME,
    NullPhotoCapture,
    OriginalPhotoCapture,
)
from src.modules.ab_tests.services.storage import StoredImage

NM_FLOWER_DRESS = 995716075

#: The rendition WB actually serves — `hq` is advertised and 404s. See
#: `WBCardPhoto`, and the live measurement behind it (2026-09-07).
MAIN_PHOTO = "https://basket-44.wbbasket.ru/vol19355/part1935545/1935545812/images/big/1.webp"
SECOND_PHOTO = "https://basket-44.wbbasket.ru/vol19355/part1935545/1935545812/images/big/2.webp"

WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 2048


@dataclass
class _Written:
    """One image handed to the media store."""

    content: bytes
    content_type: str
    test_id: uuid.UUID


class _FakeStore:
    """Records what was stored and hands back a content-addressed path."""

    def __init__(self) -> None:
        self.written: list[_Written] = []

    async def save(self, *, content: bytes, content_type: str, test_id: uuid.UUID) -> StoredImage:
        self.written.append(_Written(content, content_type, test_id))
        return StoredImage(
            relative_path=f"{test_id}/deadbeef.webp", sha256="deadbeef", size_bytes=len(content)
        )

    async def read(self, relative_path: str) -> bytes:
        raise NotImplementedError

    async def delete(self, relative_path: str) -> None:
        raise NotImplementedError


class _FakeVariants:
    """Records the original the capture files, the way the repository would."""

    def __init__(self) -> None:
        self.originals: list[dict[str, object]] = []

    async def add_original(self, **kwargs: object) -> AbTestVariant:
        self.originals.append(kwargs)
        return AbTestVariant(
            id=uuid7(),
            test_id=kwargs["test_id"],
            position=0,
            image_path=str(kwargs["image_path"]),
            image_sha256=str(kwargs["image_sha256"]),
            content_type=str(kwargs["content_type"]),
            original_filename=str(kwargs["original_filename"]),
            is_original=True,
        )


class _FakeClient:
    """Stands in for the Content client's card read."""

    def __init__(
        self, photos: list[str] | None = None, *, fail_with: Exception | None = None
    ) -> None:
        self.photos = photos if photos is not None else []
        self._fail_with = fail_with
        self.asked: list[int] = []

    async def fetch_card_photos(self, *, nm_id: int) -> list[str]:
        self.asked.append(nm_id)
        if self._fail_with is not None:
            raise self._fail_with
        return self.photos


class _FakeDownloader:
    """Stands in for the CDN fetch."""

    def __init__(
        self,
        content: bytes = WEBP,
        content_type: str = "image/webp",
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self.content = content
        self.content_type = content_type
        self._fail_with = fail_with
        self.fetched: list[str] = []

    async def download(self, url: str) -> tuple[bytes, str]:
        self.fetched.append(url)
        if self._fail_with is not None:
            raise self._fail_with
        return self.content, self.content_type


def _test() -> AbTest:
    """A draft test over one real article."""
    return AbTest(id=uuid7(), workspace_id=uuid7(), nm_id=NM_FLOWER_DRESS, name="Тест фото")


def _capture(
    client: _FakeClient, downloader: _FakeDownloader
) -> tuple[OriginalPhotoCapture, _FakeStore]:
    """Assemble the capture over fakes, returning it with its store."""
    store = _FakeStore()
    return (
        OriginalPhotoCapture(content_client=client, downloader=downloader, media_store=store),
        store,
    )


async def test_the_cards_main_photo_is_stored_as_the_original_variant() -> None:
    """The first gallery slot — and only it — becomes the rotation's original."""
    client = _FakeClient([MAIN_PHOTO, SECOND_PHOTO])
    downloader = _FakeDownloader()
    capture, store = _capture(client, downloader)
    variants = _FakeVariants()
    test = _test()

    variant = await capture.capture(test=test, variants=variants)

    assert downloader.fetched == [MAIN_PHOTO]
    assert store.written == [_Written(WEBP, "image/webp", test.id)]
    assert variant is not None
    assert variant.is_original is True
    assert variant.position == 0
    assert variants.originals[0]["original_filename"] == ORIGINAL_FILENAME


async def test_a_card_with_no_photos_captures_nothing() -> None:
    """A card WB holds no images for leaves the rotation to the uploads."""
    client = _FakeClient([])
    downloader = _FakeDownloader()
    capture, store = _capture(client, downloader)
    variants = _FakeVariants()

    assert await capture.capture(test=_test(), variants=variants) is None
    assert downloader.fetched == []
    assert store.written == []


@pytest.mark.parametrize(
    ("client", "downloader"),
    [
        pytest.param(
            _FakeClient(fail_with=RuntimeError("WB is down")),
            _FakeDownloader(),
            id="wb refuses the card read",
        ),
        pytest.param(
            _FakeClient([MAIN_PHOTO]),
            _FakeDownloader(fail_with=RuntimeError("connection reset")),
            id="the CDN drops the download",
        ),
        pytest.param(
            _FakeClient([MAIN_PHOTO]),
            _FakeDownloader(content=b"", content_type="image/webp"),
            id="the CDN serves an empty body",
        ),
        pytest.param(
            _FakeClient([MAIN_PHOTO]),
            _FakeDownloader(content_type="text/html"),
            id="the CDN serves something that is not an image",
        ),
    ],
)
async def test_a_failed_capture_degrades_instead_of_raising(
    client: _FakeClient, downloader: _FakeDownloader
) -> None:
    """Nothing about the capture may turn «Запустить» into an error."""
    capture, store = _capture(client, downloader)
    variants = _FakeVariants()

    assert await capture.capture(test=_test(), variants=variants) is None
    assert variants.originals == []
    assert store.written == []


@pytest.mark.parametrize(
    "url",
    [
        pytest.param(MAIN_PHOTO, id="the CDN host WB actually serves"),
        pytest.param("https://wbbasket.ru/x/1.webp", id="the bare allow-listed domain"),
        pytest.param("https://images.wb.ru/1.webp", id="a subdomain of an allowed one"),
    ],
)
def test_wb_image_hosts_are_fetchable(url: str) -> None:
    """The URLs WB really returns pass the allowlist."""
    assert is_wb_photo_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://basket-44.wbbasket.ru/1.webp", id="plain http"),
        pytest.param("https://notwbbasket.ru/1.webp", id="a host that merely ends the same"),
        pytest.param("https://wbbasket.ru.evil.example/1.webp", id="the domain as a prefix"),
        pytest.param("http://169.254.169.254/latest/meta-data/", id="the cloud metadata service"),
        pytest.param("file:///etc/passwd", id="a local file"),
        pytest.param("https://localhost:8000/api/v1/organizations/me", id="our own API"),
    ],
)
def test_everything_else_is_refused(url: str) -> None:
    """A URL named by an upstream is not a licence to issue the request."""
    assert is_wb_photo_url(url) is False


async def test_a_workspace_with_no_wb_token_still_gets_an_enroller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating a test may not require credentials the seller has not pasted yet.

    The refusal belongs on the start route, which writes to the live card. This
    one only reads, and a test with no baseline is a working test — the start
    fills it in. Requiring the token here broke the end-to-end flow that creates
    a test on a fresh workspace, which is how it was caught.
    """

    async def _no_tokens(session: object, *, workspace_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(ab_deps, "load_workspace_token_bundle", _no_tokens)

    enroller = await ab_deps.get_original_capture(
        session=None,  # type: ignore[arg-type]
        workspace_id=uuid7(),
        media_store=_FakeStore(),
    )

    assert isinstance(enroller, NullPhotoCapture)
    assert await enroller.enrol(test=_test(), variants=_FakeVariants()) is None


def test_the_main_photo_takes_the_rendition_wb_actually_serves() -> None:
    """`hq` is in every payload and 404s on the CDN; `big` is the real file.

    Measured across three cards on 2026-09-07. Getting this backwards is not an
    error anywhere — the capture reads a failed fetch as "no baseline" — so it
    would have shipped as every test quietly running without one.
    """
    photo = WBCardPhoto.model_validate(
        {
            "hq": "https://basket-44.wbbasket.ru/x/images/hq/1.webp",
            "big": "https://basket-44.wbbasket.ru/x/images/big/1.webp",
            "square": "https://basket-44.wbbasket.ru/x/images/square/1.webp",
        }
    )

    assert photo.best.endswith("/big/1.webp")
