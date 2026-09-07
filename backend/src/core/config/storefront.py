"""Public WildBerries storefront settings: the card endpoint.

The one surface a shopper's browser talks to that we still read
(``card.wb.ru``), which no seller API can answer for: the final price after
WB's own loyalty discount. Unauthenticated, behind an anti-bot edge, and
therefore configured apart from the seller APIs in
:mod:`src.core.config.wildberries`.

Every default below is a measurement rather than a preference; the comments
record what was measured and when, because each one has already been set the
other way at least once.

``search.wb.ru`` was the other half of this module until 2026-08-27, when the
live-position feature was removed — see ``docs/monitoring/LIVE_POSITION.md``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class StorefrontSettings(BaseSettings):
    """Card endpoint host, proxying, timeouts and retry budget."""

    # --- Card endpoint (final customer price) ---
    # Public storefront card endpoint (card.wb.ru) — the final customer price
    # after ALL discounts incl. WB loyalty (СПП). Unauthenticated. ``dest`` is a
    # region/delivery code and ``spp`` the loyalty tier the storefront prices
    # against; both are fixed inputs the СПП is computed relative to.
    wb_card_base_url: str = Field(default="https://card.wb.ru")
    wb_card_dest: int = Field(default=-1255563)
    wb_card_spp: int = Field(default=30)
    # Optional forward proxy for card.wb.ru ONLY (the other WB surfaces are
    # authenticated seller APIs reached directly). The public storefront edge
    # IP-blocks datacenter egress (prod started getting HTTP 403 on 2026-07-14);
    # a residential/mobile proxy restores the clean egress IP. curl still
    # supplies the TLS fingerprint that clears the anti-bot filter — the proxy
    # only swaps the IP. EMPTY = direct connection (correct for a clean local
    # IP). Holds credentials → lives in .env, never committed.
    wb_card_proxy: str = Field(default="")
    # Strict connect timeout for the (slow, fragile) proxy tunnel — separate
    # from the whole-request cap so a dead tunnel fails fast instead of burning
    # the full timeout budget (bounds proxy traffic/cost on failure).
    #
    # Five, measured on 2026-09-07: a tunnel the proxy is willing to open is
    # open in ~0.01 s (worst of ten runs from the worker: 0.02 s), and one it
    # refuses is never opened at all — it sits until this timeout fires. So
    # every second here is spent only on requests that were already lost, and
    # at 15 s a batch's three attempts spent 45 s before giving up, inside a
    # harvest that is holding its place in a queue of other work.
    wb_card_connect_timeout_seconds: float = Field(default=5.0)
    # Tighter retry cap than the rate-limited seller APIs: a broken proxy must
    # give up quickly instead of spinning (protects the proxy balance).
    wb_card_max_retries: int = Field(default=3)
