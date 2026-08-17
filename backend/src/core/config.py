"""Application configuration loaded from the environment.

Settings are parsed once at import time into a cached ``Settings`` singleton so
that every layer (API process, Celery worker, Alembic) reads an identical,
fully-validated configuration object.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "production"]

#: Placeholder secrets shipped in defaults / ``.env.example``. A production
#: deployment that still carries one of these has forgotten to configure the
#: environment — startup must fail rather than run with a forgeable key.
_PLACEHOLDER_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "change-me",
        "change-me-in-prod",
        "change-me-super-secret-key",
        "insecure-development-key",
        "redis-dev-password",
    }
)


class Settings(BaseSettings):
    """Strongly-typed, validated application settings.

    Values are read from environment variables (or a local ``.env`` file). All
    fields are explicitly typed to satisfy ``mypy --strict`` and to fail fast on
    a malformed deployment configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = Field(default="Marketplace Service")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # --- PostgreSQL ---
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="marketplace")
    postgres_user: str = Field(default="marketplace")
    postgres_password: str = Field(default="change-me")

    # --- Redis ---
    redis_host: str = Field(default="redis")
    redis_port: int = Field(default=6379)
    redis_db: int = Field(default=0)
    redis_password: str = Field(default="")

    # --- Security / JWT ---
    jwt_secret_key: str = Field(default="insecure-development-key")
    jwt_algorithm: str = Field(default="HS256")
    access_token_ttl_seconds: int = Field(default=900)
    refresh_token_ttl_seconds: int = Field(default=604800)
    # Hard ceiling on one login lineage: rotation slides the 7-day refresh
    # window, but no family may outlive this many seconds from first login.
    session_absolute_lifetime_seconds: int = Field(default=2_592_000)  # 30 days
    refresh_cookie_name: str = Field(default="refresh_token")
    refresh_cookie_secure: bool = Field(default=True)
    # Must match where the auth endpoints are actually mounted so the browser
    # sends the cookie back to /refresh and /logout (they live under /api).
    refresh_cookie_path: str = Field(default="/api/v1/auth")

    # --- Registration & auth abuse protection ---
    # Monitoring data is single-tenant (one seller account), so registration is
    # gated: empty code == registration disabled entirely.
    registration_invite_code: str = Field(default="")
    # Fixed-window per-IP throttle applied to /register and /login (guessable
    # secrets: passwords, invite codes).
    auth_rate_limit_attempts: int = Field(default=10)
    auth_rate_limit_window_seconds: int = Field(default=60)
    # /refresh gets its OWN budget: its secret is an unguessable 256-bit cookie
    # (throttling is abuse damping, not brute-force defense), and every page
    # load fires a silent refresh — sharing the tight login budget bounced
    # legitimate sessions to /login whenever the window was exhausted.
    refresh_rate_limit_attempts: int = Field(default=60)

    # --- CORS (browser frontend) ---
    # In production the SPA is served by nginx on the SAME origin as the API
    # (/api/ reverse proxy), so cross-origin requests never happen and the
    # middleware is disabled (CORS_ENABLED=false). Locally the Vite dev server
    # may still call the API cross-origin, so it stays enabled by default.
    cors_enabled: bool = Field(default=True)
    # Comma-separated origins allowed to call the API with credentials.
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"])

    # --- Workspace token encryption ---
    # Fernet key encrypting per-workspace WB API tokens at rest
    # (workspaces.workspace_tokens). WB tokens no longer live in the
    # environment — they are stored encrypted in the database, one set per
    # workspace. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_secret_key: str = Field(default="")

    # --- WildBerries integration ---
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
    # The ONE FBS warehouse whose stock is harvested, and the label it shows
    # under in the stock and balance tables.
    #
    # Deliberately a single id rather than a list: the account owns five FBS
    # warehouses but four are test/cross-border stubs holding nothing (verified
    # 2026-08-13), and enabling them would spend rate budget to write zeroes.
    # ``0`` disables FBS harvesting entirely.
    #
    # The label is configured rather than taken from WB because the seller's own
    # warehouse name is a working note («Иван  - Москва (Внуково) НЕ
    # УДАЛЯТЬ!!!») that would become a column header — and because
    # ``warehouse_name`` is a primary-key column, so a rename in the WB portal
    # would otherwise orphan every stored snapshot row and «Отгрузить» mark.
    wb_fbs_warehouse_id: int = Field(default=9945803, ge=0)
    wb_fbs_warehouse_label: str = Field(default="Москва (Внуково) (FBS)")
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
    wb_card_connect_timeout_seconds: float = Field(default=15.0)
    # Tighter retry cap than the rate-limited seller APIs: a broken proxy must
    # give up quickly instead of spinning (protects the proxy balance).
    wb_card_max_retries: int = Field(default=3)
    # Public storefront SEARCH endpoint (search.wb.ru) — the organic ranking a
    # shopper sees, which no seller API exposes. Unauthenticated, and behind the
    # same anti-bot edge as the card endpoint, whose proxy it inherits (see
    # ``wb_search_proxy``). Its timeout and retry budget are its OWN, and far
    # tighter, because this surface is read while a user waits.
    wb_search_base_url: str = Field(default="https://search.wb.ru")
    # The API version is a knob because WB retires them abruptly, and a retired
    # version is indistinguishable from a rate limit: it answers 429 to
    # everything. That is exactly what happened between 2026-08-14 (v14 verified
    # serving full pages) and 2026-08-17, when v14 began refusing every request
    # from every IP, direct or proxied, with or without the storefront's headers
    # — while v18 answered 200 with 100 products in the same minute.
    #
    # v18 is what the storefront itself calls today. It reaches it through
    # ``www.wildberries.ru/__internal/u-search/…``, which is NOT usable here: that
    # path is fronted by wbaas and answers 403 to any client without the
    # browser's JS-issued ``x_wbaas_token``. The same version on the API host
    # serves us directly.
    wb_search_path: str = Field(default="/exactmatch/ru/common/v18/search")
    # Delivery region the ranking is computed for (see wb_card_dest). This is the
    # value the storefront itself sends for Moscow today, captured from its own
    # request on 2026-08-17; the previous `-1257786` still answered, but matching
    # the storefront removes one difference between our request and the one WB
    # serves without complaint.
    #
    # Verified 2026-08-15: within Russia this ranking is not regionalized — this
    # value and every Russian dest WB's geo resolver hands out (СПб -1198054,
    # Екатеринбург -5818883, Новосибирск -364764) returned the SAME 100 ids in
    # the same order. It stays a knob because a non-Russian storefront IS a
    # different catalogue (.kg, dest=286: 5 178 results against 7 486, and the
    # same SKU at 53 instead of 26), which is the first thing to check when a
    # seller reports a position we disagree with.
    wb_search_dest: int = Field(default=1259570991)
    # Result slots per page; 100 is what the storefront itself requests.
    wb_search_page_size: int = Field(default=100, ge=1, le=300)
    # How deep a position probe may scan — ONE page, the top 100.
    #
    # Was 3. Each page is a separate request against a host that refuses roughly
    # two attempts in three, so depth was buying rank 101-300 at the price of
    # tripling the requests, tripling the rate-budget spend, and tripling the
    # chances of a check ending in «повторите через минуту». A card outside the
    # first 100 is not being found by shoppers either, so "не в первой сотне" is
    # the same decision for the seller as "не в первых трёхстах" — at a third of
    # the cost.
    wb_search_max_pages: int = Field(default=1, ge=1, le=20)
    # Gap between phrases in a scheduled pinned-position run. Not politeness:
    # this host answers back-to-back requests with 429 even one per 25 s (see
    # the search client's module docstring), so a run that hurries returns
    # nothing at all. One phrase a minute is what measured as sustainable.
    wb_search_probe_spacing_seconds: float = Field(default=60.0, ge=0)
    # Phrases one scheduled run may probe, per workspace. At the spacing above
    # this is the run's wall-clock budget (60 = about an hour). Pins beyond it
    # keep their previous position and are named in the run's log — a silently
    # truncated run would leave stale cards looking current.
    wb_search_max_keywords_per_run: int = Field(default=60, ge=1)
    # How long a keyword's probe result is reused (Redis). The ranking moves
    # within the hour, so this trades freshness for not being throttled: a team
    # of five checking the same phrase pays for one probe.
    wb_search_cache_seconds: int = Field(default=600, ge=0)
    # Forward proxy for the public search host. ``card`` (the default) reuses
    # ``wb_card_proxy``; ``direct`` forces a direct connection; any other value is
    # used as the proxy URL; empty means direct too.
    #
    # Proxied on purpose, and this flip-flopped once on bad evidence. On
    # 2026-08-15 a two-request comparison said direct won (200 direct vs 429
    # proxied) — but that was measured while WB was retiring the API version we
    # were calling, so the sample was noise, and we shipped `direct` on it.
    # What actually holds (2026-08-17): the block is per-IP REPUTATION, not a
    # quota, and it escalates — the VPS address earns HTTP 498 from the storefront
    # and 429 from the search host once warm, while the proxy hands out a fresh
    # residential IP per request (verified: 198.51.100.31 -> 198.51.100.32 ->
    # 198.51.100.33). Since we cannot present a browser's JS-issued wbaas token,
    # a clean IP per probe is the only lever left. It costs ~216 KB of billed
    # traffic per page.
    wb_search_proxy: str = Field(default="card")
    # Per-request cap for one search page, tighter than the shared 30s: a ranked
    # page is ~220 KB served in well under a second when the host is willing, so
    # a slow read here means throttling, and waiting the full 30s only delays
    # the retry. Bounds the probe's worst case together with the two knobs below
    # (pages x attempts x this + waits), which must stay under the browser's own
    # budget in frontend/src/modules/monitoring/api.js.
    wb_search_timeout_seconds: float = Field(default=12.0, gt=0)
    # Opening the proxy tunnel is the slow part — far slower than the answer —
    # and it gets its own ceiling so the read budget above does not have to be
    # sized for it. A dead tunnel then fails in 20s instead of burning a slot.
    wb_search_connect_timeout_seconds: float = Field(default=20.0, gt=0)
    # Retry budget for ONE search page, deliberately far tighter than the seller
    # APIs' (4). A probe is INTERACTIVE: someone is watching a spinner, and the
    # seller-API ladder (4 retries, 2/4/8/16s backoff, plus a Retry-After WB
    # sets as high as 60s) can push a single page past a minute — three pages
    # past three. Throttling here is the normal state, not an incident, so the
    # probe reports «WB притормозил» quickly and lets the user retry into a
    # warm cache instead of holding the request open.
    wb_search_max_retries: int = Field(default=1, ge=0)
    # The wait before that retry, and it has to be long enough to OUTLAST a
    # throttle window rather than merely to look patient. Measured on prod
    # 2026-08-15: a 1.5s retry was refused every time (429, retry 1/1 in 1.5s,
    # 429 — the whole probe gave up in two seconds) because this host's window is
    # tens of seconds. Retrying inside it spends an attempt to learn nothing.
    # 30s is one window; a second retry would push the worst case past the
    # browser's budget for no extra odds.
    wb_search_retry_backoff_seconds: float = Field(default=30.0, ge=0)
    # The SCHEDULED run's budget, which is the opposite trade: nobody is watching
    # it, so waiting out several throttle windows is strictly better than
    # returning early with nothing. Measured on prod 2026-08-17: the interactive
    # budget (one retry, 30s) lost the only pinned phrase to two consecutive
    # 429s, and the run reported SUCCESS having updated nothing.
    # Five, not three: every attempt is an INDEPENDENT draw, because the proxy
    # opens a new tunnel and therefore presents a new residential IP each time.
    # Measured success is roughly one attempt in three, so three attempts clear
    # ~70% and five clear ~87% — and out here the extra minutes cost nothing but
    # the worker's patience. Bounded by the per-run keyword ceiling, so a large
    # pin list still cannot outlive the run's lock.
    wb_search_task_max_retries: int = Field(default=5, ge=0)
    # FLAT, not exponential: the ceiling equals the base, so the ladder is
    # 60s + 60s + … rather than 60 + 120 + 120 + 120. Doubling made no sense
    # against a limiter whose window is tens of seconds — it did not improve the
    # odds of the next draw, it just pushed one check to ~9 minutes (observed
    # 2026-08-17 on «брюки мужской»). Five flat waits bound a check at ~5 min,
    # which is a promise the panel can make.
    wb_search_task_retry_backoff_seconds: float = Field(default=60.0, ge=0)
    wb_search_task_retry_max_backoff_seconds: float = Field(default=60.0, ge=0)
    # Ceiling on a single wait. Passed BOTH as the backoff cap and as the
    # client's Retry-After ceiling: a server-demanded wait is otherwise honoured
    # past the backoff cap (correct for the harvest, wrong for a watched
    # request), and an unbounded 900s header would hang the page. Sized so one
    # retry still fits well inside the browser's 120s budget: worst case per page
    # is timeout + wait + timeout = 12 + 30 + 12 = 54s.
    wb_search_retry_max_backoff_seconds: float = Field(default=30.0, ge=0)
    # Relative paths resolve against the backend working directory.
    # disables caching entirely. Relative paths resolve against the backend
    # working directory; a bind mount or S3 can replace it without code changes.
    # How many built packages to keep. Each is a few MB, and a full disk on this
    # box has taken the API down before, so the oldest are pruned.
    finreports_package_cache_entries: int = Field(default=24, ge=1)
    # .cache), keyed by a content digest of its inputs. The entry is only a
    # cost saver — correctness comes from the digest, not the clock — so the TTL
    # just bounds Redis growth for windows that stop being asked for. 0 disables
    # caching entirely.
    finreports_summary_cache_ttl_seconds: int = Field(default=1209600, ge=0)
    # Fake WB harvesting for LOCAL development. When on, the harvest tasks build
    # synthetic WB clients instead of the real HTTP ones (see
    # ``src.integrations.wildberries.build_*_client``): no request ever leaves
    # the box, and deterministic, plausible rows are written to the real tables
    # so the UI and pipeline stay debuggable without burning WB's rate budget.
    #
    # The code path is IDENTICAL to production — only this flag differs — so
    # local and prod never diverge. It is refused outright on any non-local
    # environment (see ``_enforce_production_hardening``): fabricated analytics
    # must never reach a real seller's dashboard, so prod cannot even boot with
    # it on. EMPTY/false everywhere but a developer's own ``.env``.
    wb_fake_harvest: bool = Field(default=False)
    wb_http_timeout_seconds: float = Field(default=30.0)
    # WB (esp. the advertising surface) is aggressively rate-limited (~1 req/min
    # -> HTTP 429). Requests retry with exponential backoff, honouring any
    # Retry-After header. Backoff sequence: base * 2**(attempt-1).
    wb_max_retries: int = Field(default=4)
    wb_retry_backoff_seconds: float = Field(default=2.0)
    wb_retry_max_backoff_seconds: float = Field(default=60.0)
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
    # The public search host, whose budget we were spending three times over per
    # button press. Verified 2026-08-17: the probe fetched its pages with no gap
    # at all ("sequential" is not "paced"), so ONE press sent three requests
    # inside a second — enough to trip the edge on its own first page and leave
    # the next press inside the penalty window it had just created. That is what
    # "429 every second try" was.
    #
    # Unlike the seller APIs this is not a published quota but an anti-bot
    # reputation system (a burst earns «Подозрительная активность» with a
    # countdown, IP-wide), so the bucket is deliberately meaner than any measured
    # header: one request at a time, ~30s apart. Capacity 1 means no burst is
    # possible even across the api and worker processes, which share this key —
    # nothing else here coordinates them.
    wb_search_bucket_capacity: int = Field(default=1, ge=1)
    wb_search_bucket_refill_seconds: float = Field(default=30.0, gt=0)
    # Longest a probe may queue for a slot. Sized under the browser's own budget
    # so a watched request that cannot get a slot says «повторите через минуту»
    # instead of timing out: 2 pages x (30s wait + 12s request) fits in 90s.
    wb_search_max_queue_seconds: float = Field(default=90.0, gt=0)
    # Kept as a separate knob, now equal to the scheduled depth: one page is
    # already the right answer for both, and a future deeper scan should have to
    # justify itself on the watched path first.
    wb_search_interactive_max_pages: int = Field(default=1, ge=1, le=20)
    # Escape hatch: disables Redis-backed pacing (tests and any environment
    # with no Redis). The clients then fall back to per-process spacing.
    wb_rate_pacing_enabled: bool = Field(default=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN built for the ``asyncpg`` driver."""
        return self._postgres_dsn("postgresql+asyncpg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN (psycopg) used by Alembic migrations only."""
        return self._postgres_dsn("postgresql+psycopg")

    def _postgres_dsn(self, scheme: str) -> str:
        """Build a Postgres DSN with URL-encoded credentials.

        ``PostgresDsn.build`` does not percent-encode its inputs, so a rotated
        password containing ``@``, ``:`` or ``/`` would produce an unparseable
        URL and crash every process at import time. Encode defensively.
        """
        dsn = PostgresDsn.build(
            scheme=scheme,
            username=quote(self.postgres_user, safe=""),
            password=quote(self.postgres_password, safe=""),
            host=self.postgres_host,
            port=self.postgres_port,
            path=self.postgres_db,
        )
        return str(dsn)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """Redis DSN shared by the Celery broker, result backend, and caches."""
        dsn = RedisDsn.build(
            scheme="redis",
            password=quote(self.redis_password, safe="") or None,
            host=self.redis_host,
            port=self.redis_port,
            path=str(self.redis_db),
        )
        return str(dsn)

    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in the production environment."""
        return self.environment == "production"

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        """Refuse to start any non-local environment with placeholder secrets
        or debug mode.

        A missing/misspelled env var silently falls back to the insecure
        defaults above; on a deployed environment (staging or production) that
        means a publicly known HS256 key (anyone can forge access tokens) or
        interactive tracebacks. Failing at startup turns a silent compromise
        into an obvious deploy error. Only ``local`` is exempt.
        """
        if self.environment == "local":
            return self

        problems: list[str] = []
        if self.jwt_secret_key in _PLACEHOLDER_SECRETS:
            problems.append("JWT_SECRET_KEY is unset or a known placeholder")
        elif len(self.jwt_secret_key) < 32:
            problems.append("JWT_SECRET_KEY must be at least 32 characters")
        if self.postgres_password in _PLACEHOLDER_SECRETS:
            problems.append("POSTGRES_PASSWORD is unset or a known placeholder")
        if self.fernet_secret_key in _PLACEHOLDER_SECRETS:
            problems.append("FERNET_SECRET_KEY is unset (required to decrypt workspace WB tokens)")
        if self.redis_password in _PLACEHOLDER_SECRETS:
            problems.append("REDIS_PASSWORD is unset or a known placeholder")
        if self.debug:
            problems.append("DEBUG must be false (leaks tracebacks and SQL echo)")
        # Synthetic harvesting fabricates analytics; letting it run anywhere but
        # a developer's own box would silently poison a real seller's numbers.
        if self.wb_fake_harvest:
            problems.append("WB_FAKE_HARVEST must be off (it writes fabricated WB data)")

        if problems:
            raise ValueError(
                f"Refusing to start with ENVIRONMENT={self.environment}: "
                + "; ".join(problems)
                + "."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    The ``lru_cache`` guarantees the environment is parsed exactly once, so the
    same immutable configuration is shared across FastAPI dependencies, Celery
    tasks, and CLI entrypoints.
    """
    return Settings()


settings: Settings = get_settings()
