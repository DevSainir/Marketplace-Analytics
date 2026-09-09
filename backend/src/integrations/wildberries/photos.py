"""What counts as a WildBerries card image URL.

WB serves every card rendition from ``basket-NN.wbbasket.ru`` (verified live
2026-09-07). The check lives here, next to the schemas that parse those URLs
out of WB's payload, because two callers now need the same answer for two
different reasons and a second copy would drift:

* :mod:`src.modules.ab_tests.services.original` **fetches** the URL, so an
  unchecked host is SSRF — a request to whatever an upstream names, however
  well authenticated that upstream was.
* :mod:`src.modules.monitoring.services.ingestion.catalog` **stores** it to be
  rendered as an ``<img src>``, so an unchecked host is a third party told
  which of our users is looking at which card, from inside our own page.

Neither caller can assume the other validated: this is the one place that says
what a WB image URL is.
"""

from __future__ import annotations

from urllib.parse import urlparse

#: Registrable domains a WB card image may sit on.
ALLOWED_PHOTO_HOSTS: frozenset[str] = frozenset({"wbbasket.ru", "wb.ru"})


def is_wb_photo_url(url: str) -> bool:
    """Is ``url`` an https link to a WB image host?

    Args:
        url: Candidate photo URL from WB's card payload.

    Returns:
        ``True`` when the scheme is https and the host is, or is a subdomain
        of, an entry in :data:`ALLOWED_PHOTO_HOSTS`. Suffix matching is on a
        dot boundary, so ``notwbbasket.ru`` does not pass and neither does
        ``wbbasket.ru.evil.example``.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in ALLOWED_PHOTO_HOSTS)


__all__ = ["ALLOWED_PHOTO_HOSTS", "is_wb_photo_url"]
