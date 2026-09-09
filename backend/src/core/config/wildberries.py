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
    # Search clusters («Поиск по кластерам»): the per-cluster grain of the SAME
    # ``normquery`` response the search-ZONE split is built from, so switching
    # it off saves no WB request — only the writes into
    # ``monitoring.advertising_cluster_stat_daily``. DORMANT since 2026-09-09:
    # the UI that read the table was hidden (see the DORMANT headers in
    # monitoring/routers/clusters.py and the frontend cluster block), and the
    # ingest is off with it. Note what that costs: WB serves no cluster
    # HISTORY, so every day this stays ``False`` is a day that can never be
    # backfilled — turning the feature back on starts the series from zero.
    # ``True`` here is the only line needed to resume accruing it.
    wb_search_cluster_harvest_enabled: bool = False
    # Column headers by warehouse id, written «<точка> - <город> (FBS)»: the
    # warehouse's own name first, because that is what distinguishes it from
    # its neighbours, then the city. The header is truncated to its first
    # letters in «Остатки по складам», so what a reader gets is «Внуково…» and
    # «Белая дача…» rather than two columns that both read «Москва (…».
    # The city is dropped where it would only repeat the name («Бишкек»), and
    # a warehouse with no meaningful region keeps its name alone.
    #
    # Anything absent is labelled from WB's own name, which is a seller's
    # working note. Read ONCE at discovery and then FROZEN: an entry edited
    # here changes nothing on its own, because the label in force lives in
    # ``monitoring.fbs_warehouse`` — renaming one means migrating every table
    # that stores it (see monitoring/models/fbs_warehouses.py).
    wb_fbs_warehouse_labels: dict[int, str] = Field(
        default_factory=lambda: {
            9945803: "Внуково - Москва (FBS)",  # ships
            9990254: "Белая дача - Москва (FBS)",  # ships (since 20.08)
            9931578: "Бишкек (FBS)",
            9830567: "EDBS - Бишкек (FBS)",
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
    # The advertising surface, from WB's own published table (2026-09-04):
    # ``/adv/v3/fullstats`` allows 3 requests per minute with a MINIMUM
    # INTERVAL of 20s and a burst of 1 — so the honest model is a one-token
    # bucket refilling every 20s, not a three-deep one. Sized this way because
    # the endpoint now has two consumers on the same seller token (the nightly
    # harvest and the A/B rotation poller); before the shared bucket existed,
    # three calls spread over eight minutes still collected a 429, which is
    # what an unpaced second consumer looks like.
    wb_advertising_bucket_capacity: int = Field(default=1, ge=1)
    wb_advertising_bucket_refill_seconds: float = Field(default=20.0, gt=0)
    # The statistics surface's settlement report, measured live on 2026-09-07
    # from WB's own headers: `x-ratelimit-limit: 1`, `x-ratelimit-reset: 917`.
    # ONE request per ~15 minutes per seller token — not the per-minute budget
    # the rest of this file is used to, and not something a walk can page
    # through. Worse, a request made while the bucket is empty RESTARTS the
    # window: two probes 15 minutes apart both answered 429, the second
    # demanding a fresh 917 s. So the bucket's job here is not to pace, it is
    # to make sure the request is not sent at all.
    #
    # Nothing paced it before because no seller had ever needed a second page:
    # at `limit=10000` a one-page window is the normal case, and the first
    # customer to exceed it (2026-09-07) found the 429, then the 897 s
    # retry-sleep INSIDE the harvest's open transaction, then PostgreSQL
    # closing the connection under it.
    #
    # The refill is 960 s rather than the 900 it was until 2026-09-09, and the
    # 60 s of slack is the point: WB's measured reset is 917 s, so a 900 s
    # bucket handed out its token 17 s before WB would honour it and bought a
    # 429 for the trouble. Since that 429 also RESTARTS the window, an interval
    # slightly too short is far more expensive than one slightly too long.
    # This governs only the ordinary path now — after a 429 the gate is driven
    # by WB's own `X-Ratelimit-Retry` through `RateGate.penalise`, so the
    # constant no longer has to be right about a penalty it cannot see.
    wb_statistics_bucket_capacity: int = Field(default=1, ge=1)
    wb_statistics_bucket_refill_seconds: float = Field(default=960.0, gt=0)
    # A page may queue this long for a token before the walk gives up. It is
    # deliberately FAR below one refill: the walk pages inside an open
    # transaction that PostgreSQL kills after 300 s idle, so waiting out a real
    # block here would trade a failure the harvest reports for one it cannot.
    # Failing fast leaves the window for the next tick and costs WB nothing.
    wb_statistics_max_queue_seconds: float = Field(default=45.0, gt=0)
    # What the settlement WALK may wait, as opposed to what a request inside a
    # transaction may. The walk takes its token before it opens a transaction,
    # so it can afford to sit out a whole refill — and must, because the window
    # it is waiting for is a week of a seller's money.
    wb_statistics_walk_queue_seconds: float = Field(default=1000.0, gt=0)
    # Escape hatch: disables Redis-backed pacing for EVERY bucket, the
    # storefront's included (tests and any environment with no Redis). The
    # clients then fall back to per-process spacing.
    wb_rate_pacing_enabled: bool = Field(default=True)
