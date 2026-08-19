"""WildBerries *seller* API settings: hosts, transport budget, rate buckets.

One base URL per WB surface (each authenticates with its own token category),
the FBS harvesting switch and warehouse labels, the shared HTTP timeout and
retry ladder, and the client-side token buckets that keep us inside WB's
measured rate limits.

The public, unauthenticated storefront surfaces live in
:mod:`src.core.config.storefront` — they share the vendor but nothing else:
no seller token, a different anti-bot regime, and their own far tighter
budgets.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class WildberriesSettings(BaseSettings):
    """Seller-API hosts, FBS harvesting, transport budget and pacing."""

    # --- Surface hosts ---
    wb_analytics_base_url: str = Field(default="https://seller-analytics-api.wildberries.ru")
    wb_advertising_base_url: str = Field(default="https://advert-api.wildberries.ru")
    wb_content_base_url: str = Field(default="https://content-api.wildberries.ru")
    wb_prices_base_url: str = Field(default="https://discounts-prices-api.wildberries.ru")
    wb_statistics_base_url: str = Field(default="https://statistics-api.wildberries.ru")
    wb_common_base_url: str = Field(default="https://common-api.wildberries.ru")
    # Documents surface: signed weekly-realization / acceptance-act originals
    # (finreports court-grade evidence archival).
    wb_documents_base_url: str = Field(default="https://documents-api.wildberries.ru")
    # Supplies surface: FBW supply / acceptance context (finreports gi_id join).
    wb_supplies_base_url: str = Field(default="https://supplies-api.wildberries.ru")
    # Finance surface: seller balance / settlement (finreports currency context).
    wb_finance_base_url: str = Field(default="https://finance-api.wildberries.ru")
    # Marketplace surface: seller-owned (FBS) warehouses and their stock. Needs
    # a «Маркетплейс»-scope token; no other category authenticates this host.
    wb_marketplace_base_url: str = Field(default="https://marketplace-api.wildberries.ru")
    # Every FBS warehouse WB lists for the seller is discovered and read, so a
    # warehouse opened in the portal needs no deploy. ``False`` switches FBS off.
    wb_fbs_harvest_enabled: bool = True
    # Column headers by warehouse id; anything absent is labelled from WB's own
    # name, which is a seller's working note. Read ONCE at discovery and then
    # FROZEN — see monitoring/models/fbs_warehouses.py before editing an entry.
    wb_fbs_warehouse_labels: dict[int, str] = Field(
        default_factory=lambda: {
            9945803: "Москва (Внуково) (FBS)",  # ships
            9990254: "Москва (Белая дача) (FBS)",  # ships (empty as of 19.08)
            9931578: "Бишкек (FBS)",
            9830567: "Бишкек EDBS (FBS)",
            9041173: "Тест товаров (FBS)",
            9684293: "Тест 2 (FBS)",
        }
    )

    # --- Harvesting mode and transport budget ---
    # Fake WB harvesting for LOCAL development. When on, the harvest tasks build
    # synthetic WB clients instead of the real HTTP ones (see
    # ``src.integrations.wildberries.build_*_client``): no request ever leaves
    # the box, and deterministic, plausible rows are written to the real tables
    # so the UI and pipeline stay debuggable without burning WB's rate budget.
    #
    # The code path is IDENTICAL to production — only this flag differs — so
    # local and prod never diverge. It is refused outright on any non-local
    # environment (see ``_enforce_production_hardening`` in
    # :mod:`src.core.config.assembly`): fabricated analytics must never reach
    # a real seller's dashboard, so prod cannot even boot with it on.
    # EMPTY/false everywhere but a developer's own ``.env``.
    wb_fake_harvest: bool = Field(default=False)
    wb_http_timeout_seconds: float = Field(default=30.0)
    # WB (esp. the advertising surface) is aggressively rate-limited (~1 req/min
    # -> HTTP 429). Requests retry with exponential backoff, honouring any
    # Retry-After header. Backoff sequence: base * 2**(attempt-1).
    wb_max_retries: int = Field(default=4)
    wb_retry_backoff_seconds: float = Field(default=2.0)
    wb_retry_max_backoff_seconds: float = Field(default=60.0)

    # --- Client-side rate buckets ---
    # Client-side pacing of the analytics surface, measured live on 2026-07-30
    # against seller-analytics-api: each endpoint holds a 3-token bucket per
    # seller token and refills one token within 20s (a call every 20s keeps
    # ``x-ratelimit-remaining`` pinned at 2; a call 5s later drops it to 1).
    # Overrunning it does NOT reliably answer 429 — WB returns HTTP 500, or
    # holds the connection until our read timeout — so the budget has to be
    # respected before sending, not discovered afterwards.
    wb_analytics_bucket_capacity: int = Field(default=3, ge=1)
    wb_analytics_bucket_refill_seconds: float = Field(default=20.0, gt=0)
    # A request may queue this long for a token before the client gives up. The
    # 22-day cohort pass needs ~7 min of queueing overall but never more than
    # one refill per call; anything beyond this means the budget is being
    # consumed faster than it refills, and failing lets the task's retry policy
    # reschedule instead of parking a worker.
    wb_analytics_max_queue_seconds: float = Field(default=120.0, gt=0)
    # The marketplace (FBS) surface answered ``x-ratelimit-remaining: 20`` on
    # both its endpoints when measured live on 2026-08-13. Refill is assumed
    # per-minute (WB publishes no window); the header clamp corrects us
    # downward on every response, so guessing generously here is safe.
    wb_marketplace_bucket_capacity: int = Field(default=20, ge=1)
    wb_marketplace_bucket_refill_seconds: float = Field(default=3.0, gt=0)
    # Escape hatch: disables Redis-backed pacing for EVERY bucket, the
    # storefront's included (tests and any environment with no Redis). The
    # clients then fall back to per-process spacing.
    wb_rate_pacing_enabled: bool = Field(default=True)
