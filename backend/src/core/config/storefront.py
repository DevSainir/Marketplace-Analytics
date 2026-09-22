"""Public WildBerries storefront settings: the card endpoint.

The one surface a shopper's browser talks to that we still read, which no
seller API can answer for: the final price after WB's own loyalty discount.
Unauthenticated, behind an anti-bot edge, and therefore configured apart from
the seller APIs in :mod:`src.core.config.wildberries`.

**The host moved on 2026-09-22.** ``card.wb.ru`` went to 403 for every caller
from everywhere — real Chrome included — and the storefront now reads the same
``/cards/v4/detail`` through its own domain. See
``.claude/skills/wildberries-api/references/storefront-card.md``.

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
    # Public storefront card endpoint — the final customer price after ALL
    # discounts incl. WB loyalty (СПП). Unauthenticated.
    wb_card_base_url: str = Field(default="https://www.wildberries.ru")
    # The path is a SETTING, not a constant, for the same reason the removed
    # live-position probe's was (docs/monitoring/LIVE_POSITION.md §3): WB
    # retires storefront versions without notice, and a retired one is
    # indistinguishable from a block. Measured 2026-09-22 — this is what the
    # site's own SPA requests (x-spa-version 14.25.3).
    wb_card_path: str = Field(default="/__internal/u-card/cards/v4/detail")
    # ``dest`` is the region code. Measured 2026-09-22: the historical value
    # below returns prices identical to the Moscow code the storefront itself
    # sends (1259570991), on every SKU checked — so the snapshot series
    # continues unbroken. A third region returned different prices, so the
    # parameter is still live; this one is simply Moscow's equal.
    wb_card_dest: int = Field(default=-1255563)
    # Kept for the URL's shape only. Measured 2026-09-22: ``spp=30`` and
    # ``spp=0`` return byte-identical prices — the endpoint ignores it. It was
    # decoration before the move too; we just had no way to know.
    wb_card_spp: int = Field(default=30)
    # The one header the endpoint now insists on. Measured 2026-09-22 by
    # sending each of the SPA's three headers alone: ``x-requested-with`` and
    # ``x-spa-version`` change nothing, ``deviceid`` alone turns 403 into 200.
    # The value is arbitrary — a made-up one was accepted, so it carries no
    # signature and is not a credential. It is NOT an anti-bot bypass either:
    # without a storefront session the answer is 498 (wbaas captcha page)
    # whatever this is set to.
    wb_card_device_id: str = Field(default="site_9f2c41b7ae5d4e0c8b6a37d1e4f05c29")
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
