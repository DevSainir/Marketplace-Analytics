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
    # Returns surface: buyer return claims («Заявки на возврат»). Captured by
    # the `guide` module only — WB keeps them fourteen days and nothing else
    # carries the buyer's own words about why the item came back.
    wb_returns_base_url: str = Field(default="https://returns-api.wildberries.ru")
    # Feedbacks surface: reviews and buyer questions. Needs the «Вопросы и
    # отзывы» scope; every other category answers it 403.
    wb_feedbacks_base_url: str = Field(default="https://feedbacks-api.wildberries.ru")
    # Every FBS warehouse WB lists for the seller is discovered and read, so a
    # warehouse opened in the portal needs no deploy. ``False`` switches FBS off.
    wb_fbs_harvest_enabled: bool = True
    # Search clusters («Поиск по кластерам»): the per-cluster grain of the SAME
    # ``normquery`` response the search-ZONE split is built from, so switching
    # it off saves no WB request — only the writes into
    # ``monitoring.advertising_cluster_stat_daily``. DORMANT since 2026-09-09:
    # the UI that read the table was hidden (see the DORMANT headers in
    # monitoring/routers/clusters.py and the frontend cluster block), and the
    # ingest is off with it.
    #
    # This used to say the dormant days were lost forever, because WB serves no
    # cluster history. **That was wrong.** Probed on prod 2026-09-12: WB
    # returned full daily cluster stats for 2025-10-01 — about 347 days back —
    # for a (campaign, SKU) pair that provably delivered SEARCH traffic then. So
    # the days this stays ``False`` are recoverable, bounded by the 31-day
    # window and the limiter rather than by WB's memory. Why the old reading
    # looked true is in `references/advertising.md`: the endpoint answers
    # "nothing" in two different shapes and neither is an error.
    # ``True`` here is the only line needed to resume accruing it live.
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
    # The statistics surface's DEFAULT bucket — for any path not given its own
    # in `STATISTICS_ENDPOINT_BUCKETS`. One request a minute, WB's published
    # figure for the surface. It was one per 960 s until 2026-09-24, sized for
    # the settlement report (`reportDetailByPeriod`, `x-ratelimit-reset: 917`),
    # which left this surface on 2026-09-22; kept at that figure, an unlisted
    # statistics path would have been paced at sixteen minutes a request.
    wb_statistics_bucket_capacity: int = Field(default=1, ge=1)
    wb_statistics_bucket_refill_seconds: float = Field(default=60.0, gt=0)
    # A call may queue this long for a token before it gives up — below one
    # refill, so a second call inside the minute fails fast instead of holding
    # a task. That is what stops a person leaning on «Обновить» from queueing
    # the account-wide sales feed.
    wb_statistics_max_queue_seconds: float = Field(default=45.0, gt=0)
    # The «catalogue» family — content, prices and common (tariffs). All three
    # answered `x-ratelimit-limit: 5` when probed live on 2026-09-15, and a
    # burst against common-api pinned the window down: the 6th request inside
    # 0.78 s came back 429, and the bucket refilled one token per second (empty
    # at t=0, 1 token by +1.8 s, 2 by +3.8 s, full by +8.8 s). WB sends no
    # `Retry-After` with that 429, so the client's own backoff is all there is.
    #
    # One setting pair for three surfaces because one measurement covers all
    # three. Split them the day one of them is measured to differ — not before,
    # or the numbers stop meaning «measured» and start meaning «assumed».
    #
    # These were UNPACED entirely until 2026-09-15: `BaseWBClient` defaults its
    # gate to `NullRateGate`, so a client that simply never passed one was
    # silently exempt. That is the failure mode this block exists to close, and
    # `tests/unit/integrations/test_every_wb_client_is_paced.py` is what keeps
    # the next client from repeating it.
    wb_catalogue_bucket_capacity: int = Field(default=5, ge=1)
    wb_catalogue_bucket_refill_seconds: float = Field(default=1.0, gt=0)
    # Escape hatch: disables Redis-backed pacing for EVERY bucket, the
    # storefront's included (tests and any environment with no Redis). The
    # clients then fall back to per-process spacing.
    wb_rate_pacing_enabled: bool = Field(default=True)
