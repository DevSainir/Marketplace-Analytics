"""Enrolling the photo that is already on the card into the rotation.

A test used to compare only what the seller uploaded, which answers the wrong
question. «Фото Б набрало 4 % CTR» is not a reason to change anything unless the
photo it would replace is in the same table — the one number every seller
already has, and the only baseline the decision is actually against. So
**creating** a test captures the card's current main photo from WB and rotates
it like any other variant.

Creating, not starting. The seller is choosing photos for a circle, and a
baseline that only materialises once the test is running is one they never see
themselves choosing against — and one whose row in the result table arrives as a
surprise. Enrolling it at creation is what makes «Главное» a thing on the screen
rather than an implementation detail.

It is not an upload, so three things about it differ:

* **It is captured, not chosen.** WB serves renditions, not the seller's
  original file, so what is stored is a transcoded ``.webp`` off
  ``basket-NN.wbbasket.ru`` — the largest one the card offers.
* **It goes first**, at position 0, and it is marked «Главное» in the table
  rather than numbered. It is already on the card, so its turn costs no upload
  and no moderation pass; the rotation opens by measuring the status quo and
  then starts replacing it.
* **Failing to capture it fails nothing.** WB being unreachable, or a card with
  no images at all, leaves a test that runs over the uploads alone — the old
  behaviour. The start tries again for a test created while WB was down.
  Refusing to create, or to start, would trade a complete answer for no answer.
"""

from __future__ import annotations

import uuid
from typing import Protocol
from urllib.parse import urlparse

import httpx

from src.core.logging import get_logger
from src.modules.ab_tests.models import AbTest, AbTestVariant
from src.modules.ab_tests.services.photos import MAX_IMAGE_BYTES, validate_image
from src.modules.ab_tests.services.storage import MediaStore

logger = get_logger(__name__)

#: Hosts a captured photo may be fetched from.
#:
#: The URL comes out of a WB API response, which is outside the trust boundary
#: however well authenticated it was: a fetch of a host named by an upstream is
#: SSRF whether or not that upstream is hostile today. WB serves every card
#: image from ``basket-NN.wbbasket.ru``, verified live 2026-09-07, so the
#: allowlist costs nothing and bounds what this code can be made to request.
ALLOWED_PHOTO_HOSTS: frozenset[str] = frozenset({"wbbasket.ru", "wb.ru"})

#: How long the CDN has to answer. Short: this runs inside the «Запустить»
#: request, and a slow capture must not hold the user on a spinner — the
#: fallback (start without it) is a second away.
DOWNLOAD_TIMEOUT_SECONDS: float = 10.0

#: Read granularity for the download, matching :mod:`src.core.uploads`.
_CHUNK_BYTES = 512 * 1024

#: Shown in the UI where an upload would show the user's own file name.
ORIGINAL_FILENAME = "Текущее фото карточки"


def _host_allowed(url: str) -> bool:
    """Is ``url`` an https link to a WB image host?

    Args:
        url: Candidate photo URL from WB's card payload.

    Returns:
        ``True`` when the scheme is https and the host is, or is a subdomain
        of, an entry in :data:`ALLOWED_PHOTO_HOSTS`. Suffix matching is on a
        dot boundary, so ``notwbbasket.ru`` does not pass.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_PHOTO_HOSTS)


class PhotoDownloader(Protocol):
    """Fetches the bytes behind one WB CDN image URL."""

    async def download(self, url: str) -> tuple[bytes, str]: ...


class HttpPhotoDownloader:
    """Downloads a card photo from WB's public image CDN.

    Deliberately not a :class:`~src.integrations.wildberries.clients.base.BaseWBClient`
    subclass. The basket hosts are a CDN, not an API surface: they take no
    token, they are not behind the Redis rate bucket the harvester shares, and
    the retry ladder built for WB's throttling would be the wrong shape for a
    static file. This is one bounded GET.
    """

    async def download(self, url: str) -> tuple[bytes, str]:
        """Return ``(bytes, content_type)`` for one image URL.

        Streamed and cut off at :data:`MAX_IMAGE_BYTES`, for the same reason
        uploads are: the ceiling has to bound memory rather than describe it
        afterwards, and the URL is named by an upstream rather than by us.

        Args:
            url: An https URL on a WB image host.

        Returns:
            The image bytes and the MIME type the CDN served them as.

        Raises:
            ValueError: If the host is not allow-listed, the response is not a
                success, or the body runs past the ceiling.
            httpx.HTTPError: If the CDN cannot be reached.
        """
        if not _host_allowed(url):
            raise ValueError(f"Refusing to fetch a card photo from an unexpected host: {url}")

        async with (
            httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS) as client,
            client.stream("GET", url) as response,
        ):
            if response.status_code != httpx.codes.OK:
                raise ValueError(f"WB CDN answered {response.status_code} for {url}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes(_CHUNK_BYTES):
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ValueError(f"Card photo at {url} is larger than the upload ceiling.")
                chunks.append(chunk)
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
        return b"".join(chunks), content_type


class CardPhotoSource(Protocol):
    """The part of ``WBContentClient`` the capture needs."""

    async def fetch_card_photos(self, *, nm_id: int) -> list[str]: ...


class _VariantSink(Protocol):
    """The part of ``VariantRepository`` the capture writes through."""

    async def add_original(
        self,
        *,
        test_id: uuid.UUID,
        image_path: str,
        image_sha256: str,
        content_type: str,
        original_filename: str,
    ) -> AbTestVariant: ...


class OriginalPhotoCapture:
    """Copies a card's live main photo into a test as its first variant."""

    def __init__(
        self,
        *,
        content_client: CardPhotoSource,
        downloader: PhotoDownloader,
        media_store: MediaStore,
    ) -> None:
        """Wire the capture to WB, the CDN and the image store.

        Args:
            content_client: Reads the card's gallery URLs.
            downloader: Fetches the bytes behind the main photo's URL.
            media_store: Where the captured original is written, alongside the
                uploads — so the rotation, the result table and the image route
                all read one kind of thing.
        """
        self._client = content_client
        self._downloader = downloader
        self._store = media_store

    async def enrol(self, *, test: AbTest, variants: _VariantSink) -> AbTestVariant | None:
        """Put the card's photo in the rotation if it is not already there.

        Idempotent, and that matters twice. Creating a test enrols it, so the
        seller sees it in the list before uploading anything; starting one
        enrols it again for the test whose creation happened while WB was out of
        reach. Neither may produce a second copy at a position that is taken.

        The loaded ``variants`` collection is kept in step with the INSERT,
        because the caller has to report ``variant_count`` in the same request.

        Args:
            test: The test, with its variants loaded.
            variants: Repository the new row is written through.

        Returns:
            The card's photo as a variant — the one already enrolled, the one
            just captured, or ``None`` when there was nothing to capture.
        """
        existing = next((variant for variant in test.variants if variant.is_original), None)
        if existing is not None:
            return existing

        captured = await self.capture(test=test, variants=variants)
        if captured is not None:
            # Front of the list, because that is where position 0 sorts.
            test.variants.insert(0, captured)
        return captured

    async def capture(self, *, test: AbTest, variants: _VariantSink) -> AbTestVariant | None:
        """Enrol the card's current main photo, or return ``None``.

        Every failure here is swallowed into ``None`` and a warning. This runs
        inside «Запустить», and the alternative to a test that compares the
        uploads against the status quo is a test that does not start at all —
        so a card with no images, an unreachable CDN, or a rendition WB serves
        in some format we do not accept all degrade to the old behaviour rather
        than to an error the seller cannot act on.

        Args:
            test: The test being started. Supplies the article and the id the
                stored object is filed under.
            variants: Repository the new row is written through.

        Returns:
            The captured variant, or ``None`` when there was nothing to capture.
        """
        try:
            urls = await self._client.fetch_card_photos(nm_id=test.nm_id)
        except Exception as exc:
            logger.warning(
                "ab_tests: could not read the card's photos for nm_id=%s: %s", test.nm_id, exc
            )
            return None

        if not urls:
            logger.info(
                "ab_tests: card nm_id=%s has no photos; the test rotates its uploads only",
                test.nm_id,
            )
            return None

        try:
            content, content_type = await self._downloader.download(urls[0])
            validate_image(content=content, content_type=content_type)
        except Exception as exc:
            logger.warning(
                "ab_tests: could not capture the main photo of nm_id=%s: %s", test.nm_id, exc
            )
            return None

        stored = await self._store.save(content=content, content_type=content_type, test_id=test.id)
        return await variants.add_original(
            test_id=test.id,
            image_path=stored.relative_path,
            image_sha256=stored.sha256,
            content_type=content_type,
            original_filename=ORIGINAL_FILENAME,
        )


__all__ = [
    "ALLOWED_PHOTO_HOSTS",
    "DOWNLOAD_TIMEOUT_SECONDS",
    "ORIGINAL_FILENAME",
    "CardPhotoSource",
    "HttpPhotoDownloader",
    "OriginalPhotoCapture",
    "PhotoDownloader",
]
